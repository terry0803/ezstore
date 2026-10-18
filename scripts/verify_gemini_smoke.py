"""Small Gemini smoke test gated on complete local acceptance.

The only external HTTP traffic allowed is the Gemini model catalog and at most
four generation attempts. Read-only cases compare every quotation/order and its
items before and after the turn, including on failure. Run with advisor/.venv.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
import time
from contextlib import AbstractContextManager
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
BACKEND = "http://127.0.0.1:58080/api/v1"
GEMINI_HOST = "generativelanguage.googleapis.com"
REQUIRED_LOCAL_CASES = {
    "a_read", "a_customer_list", "a_duplicate", "a_factor", "a_total", "a_convert",
    "a_clarify_quote", "a_clarify_factor", "a_refusal", "a_ambiguous", "a_customer_quotation", "a_missing_quote", "a_malformed_quote",
    "b_policy", "b_apply_a2a", "b_approval", "b_negative", "b_relative", "b_stale_failure",
    "b_hypothetical", "b_unreachable", "b_order_checks", "b_convert_a2a", "b_ambiguous", "b_malformed_quote",
}


class RequestBudgetExceeded(RuntimeError):
    pass


class ApiBudget(AbstractContextManager):
    """Count attempts at HTTP boundaries, including SDK-internal retries."""

    def __init__(self, limit=4):
        self.limit = limit
        self.requests = []
        self.model = None
        self._restore = []

    def begin(self, method, url):
        parsed = urlsplit(str(url))
        if parsed.hostname in {"127.0.0.1", "localhost", "::1"}:
            return None
        if parsed.scheme != "https" or parsed.hostname != GEMINI_HOST or parsed.username or parsed.port not in (None, 443):
            raise RuntimeError("External endpoint is outside the Gemini smoke allowlist")
        generation = method.upper() == "POST" and parsed.path.endswith((":generateContent", ":streamGenerateContent"))
        catalog = method.upper() == "GET" and parsed.path.rstrip("/").endswith("/models")
        if not generation and not catalog:
            raise RuntimeError("External request is outside the Gemini smoke allowlist")
        kind = "generation" if generation else "catalog"
        count = sum(row["kind"] == kind for row in self.requests)
        if count >= (self.limit if generation else 10):
            raise RequestBudgetExceeded("HTTP request budget exhausted")
        model = parsed.path.rsplit("/", 1)[-1].split(":", 1)[0] if generation else None
        if generation and (not self.model or model != self.model):
            raise RuntimeError("Generation model differs from the selected smoke model")
        row = {"kind": kind, "attempt": count + 1, "method": method.upper()}
        if model:
            row["requested_model"] = model
        self.requests.append(row)
        return row

    @staticmethod
    def finish(row, started, response=None, error=None):
        if row is not None:
            row["elapsed_ms"] = round((time.monotonic() - started) * 1000)
            if response is not None:
                row["status"] = getattr(response, "status_code", getattr(response, "status", None))
            if error is not None:
                # URLs, headers, bodies and exception text may contain credentials.
                row["error_type"] = type(error).__name__

    def __enter__(self):
        import aiohttp
        import httpx

        budget = self
        sync_send, async_send = httpx.Client.send, httpx.AsyncClient.send
        aio_request = aiohttp.ClientSession._request

        def counted_sync(client, request, *args, **kwargs):
            row = budget.begin(request.method, request.url)
            started = time.monotonic()
            if row is not None:
                kwargs["follow_redirects"] = False
            try:
                response = sync_send(client, request, *args, **kwargs)
            except BaseException as exc:
                budget.finish(row, started, error=exc)
                raise
            budget.finish(row, started, response)
            return response

        async def counted_async(client, request, *args, **kwargs):
            row = budget.begin(request.method, request.url)
            started = time.monotonic()
            if row is not None:
                kwargs["follow_redirects"] = False
            try:
                response = await async_send(client, request, *args, **kwargs)
            except BaseException as exc:
                budget.finish(row, started, error=exc)
                raise
            budget.finish(row, started, response)
            return response

        async def counted_aio(client, method, url, *args, **kwargs):
            row = budget.begin(method, url)
            started = time.monotonic()
            if row is not None:
                kwargs["allow_redirects"] = False
            try:
                response = await aio_request(client, method, url, *args, **kwargs)
            except BaseException as exc:
                budget.finish(row, started, error=exc)
                raise
            budget.finish(row, started, response)
            return response

        self._restore = [(httpx.Client, "send", sync_send), (httpx.AsyncClient, "send", async_send),
                         (aiohttp.ClientSession, "_request", aio_request)]
        httpx.Client.send, httpx.AsyncClient.send = counted_sync, counted_async
        aiohttp.ClientSession._request = counted_aio
        return self

    def __exit__(self, *exc):
        for owner, name, original in reversed(self._restore):
            setattr(owner, name, original)
        self._restore = []
        return False


async def snapshot_backend(http):
    """Read all records and item details, rejecting incomplete pagination."""
    result = {}
    for kind, path in (("quotes", "/quotations"), ("orders", "/orders")):
        rows, page = {}, 1
        while True:
            response = await http.get(BACKEND + path, params={"page": page, "page_size": 100})
            response.raise_for_status()
            listing = response.json()
            total = int(listing["total"])
            for record in listing["data"]:
                record_id = str(record["id"])
                if record_id in rows:
                    raise RuntimeError("Duplicate ID during snapshot pagination")
                detail_response = await http.get(f"{BACKEND}{path}/{record_id}")
                detail_response.raise_for_status()
                detail = detail_response.json()
                if "items" not in detail or str(detail.get("id")) != record_id:
                    raise RuntimeError("Snapshot detail is incomplete")
                detail["items"] = sorted(detail["items"], key=lambda row: str(row["id"]))
                rows[record_id] = detail
            if len(rows) == total:
                break
            if not listing["data"] or len(rows) > total:
                raise RuntimeError("Incomplete snapshot pagination")
            page += 1
        result[kind] = rows
    return result


def snapshot_check(case, before, after):
    def digest(value):
        return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {
        "case": case, "checked": True, "unchanged": before == after,
        "before_sha256": digest(before), "after_sha256": digest(after),
        "counts_before": {kind: len(rows) for kind, rows in before.items()},
        "counts_after": {kind: len(rows) for kind, rows in after.items()},
        "changed_ids": {kind: sorted(key for key in set(before[kind]) | set(after[kind])
                                    if before[kind].get(key) != after[kind].get(key)) for kind in before},
    }


async def checked_read_only(case, ask, http, checks):
    before = await snapshot_backend(http)
    try:
        return await ask()
    finally:
        # Still check the database if generation, parsing, or an agent tool failed.
        try:
            after = await snapshot_backend(http)
        except Exception as exc:
            checks.append({"case": case, "checked": False, "error_type": type(exc).__name__})
            raise
        check = snapshot_check(case, before, after)
        checks.append(check)
        if not check["unchanged"]:
            raise AssertionError("Read-only smoke changed quotations/orders/items")


async def close_safely(name, close, errors):
    try:
        # Keep AnyIO/MCP cleanup in the task that owns its context managers.
        async with asyncio.timeout(10):
            await close()
    except Exception as exc:
        errors.append({"resource": name, "error_type": type(exc).__name__})


def save_report(output, report):
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


async def main(args):
    local = json.loads(args.local_report.read_text(encoding="utf-8"))
    passed = {row["case"] for row in local["results"] if row["passed"]}
    if (REQUIRED_LOCAL_CASES - passed or any(not row["passed"] for row in local["results"])
            or local.get("isolated_backend") != BACKEND or not local.get("model", "").startswith("openai/")):
        raise SystemExit("Complete local acceptance on the isolated stack must pass before Gemini is called")

    import httpx
    from dotenv import dotenv_values
    from google import genai
    from google.genai import types

    values = dotenv_values(ROOT / ".env")
    key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or values.get("GEMINI_API_KEY") or values.get("GOOGLE_API_KEY")
    if not key:
        raise SystemExit("Gemini key missing in environment or homework .env")
    os.environ.update({
        "PYTHON_DOTENV_DISABLED": "1", "GEMINI_API_KEY": key,
        "GOOGLE_GENAI_USE_VERTEXAI": "false", "MODEL_MAX_ATTEMPTS": "1",
        "MCP_URL": "http://127.0.0.1:58010/mcp", "BACKEND_API": BACKEND,
        "QUOTATION_AGENT_URL": "http://127.0.0.1:58501/a2a/quotation_agent",
        "FRONTEND_URL": "http://localhost:53000", "OKF_BUNDLE": str(ROOT / "knowledge" / "ezstore"),
    })
    candidates = ["gemini-2.5-flash-lite", "gemini-3.1-flash-lite", "gemini-3.5-flash-lite"]
    if getattr(args, "model", None):
        if args.model not in candidates:
            raise ValueError("Choose a supported low-cost Flash-Lite model")
        candidates = [args.model]
    skip_ambiguity = getattr(args, "skip_ambiguity_case", False)
    expected_cases = 2 if skip_ambiguity else 3
    records, responses, calls, db_checks, cleanup_errors = [], [], [], [], []
    runners, sdk_client, original_generate, Gemini, first = {}, None, None, None, None
    budget, model = ApiBudget(limit=getattr(args, "generation_limit", 4)), None
    http = httpx.AsyncClient(timeout=30, follow_redirects=False, trust_env=False)
    complete = False

    try:
        # Fail before any paid request if isolated fixture access is unavailable.
        await snapshot_backend(http)
        with budget:
            sdk_client = genai.Client(
                api_key=key, vertexai=False,
                http_options=types.HttpOptions(
                    base_url=f"https://{GEMINI_HOST}", timeout=180000,
                    retry_options=types.HttpRetryOptions(attempts=1)))
            names = {m.name.removeprefix("models/") for m in sdk_client.models.list()
                     if "generateContent" in (m.supported_actions or [])}
            model = next((name for name in candidates if name in names), None)
            if not model:
                raise RuntimeError("No preferred low-cost Flash-Lite model is available")
            budget.model = model
            os.environ["AGENT_MODEL"] = model
            sys.path[:0] = [str(ROOT / "agent"), str(ROOT / "advisor")]

            from google.adk.models import Gemini
            from google.adk.runners import InMemoryRunner
            import quotation_agent.agent as first
            import pricing_advisor.agent as second

            original_generate = Gemini.generate_content_async

            async def counted_generate(self, *positional, **kwargs):
                if len(calls) >= budget.limit:
                    raise RequestBudgetExceeded("Model invocation budget exhausted")
                entry = {"requested_model": self.model}
                calls.append(entry)
                try:
                    async for event in original_generate(self, *positional, **kwargs):
                        if event.usage_metadata:
                            entry["usage"] = event.usage_metadata.model_dump(mode="json", exclude_none=True)
                        version = getattr(event, "model_version", None)
                        if version:
                            entry["returned_model_version"] = version
                        yield event
                except Exception as exc:
                    entry["error_type"] = type(exc).__name__
                    raise

            Gemini.generate_content_async = counted_generate
            for module in (first, second):
                for node in module.root_agent.graph.nodes:
                    if isinstance(getattr(node, "model", None), Gemini):
                        # Workflow compilation clones the models. Pin the actual nodes.
                        node.model.model, node.model.client = model, sdk_client
                        config = node.generate_content_config
                        config.max_output_tokens = 512
                        config.automatic_continuation = False
                        if model.startswith("gemini-2.5"):
                            config.thinking_config = types.ThinkingConfig(thinking_budget=0)
                runners[module.APP_NAME] = InMemoryRunner(app=module.app)

            async def ask(app, prompt):
                runner = runners[app]
                session = await runner.session_service.create_session(app_name=app, user_id="gemini-smoke")
                texts = []
                async for event in runner.run_async(
                    user_id="gemini-smoke", session_id=session.id,
                    new_message=types.Content(role="user", parts=[types.Part(text=prompt)])):
                    if getattr(event, "error_code", None) or getattr(event, "error_message", None):
                        raise RuntimeError("Agent returned an error event")
                    if event.node_info and "/respond@" in event.node_info.path and event.content:
                        texts.append("".join(part.text or "" for part in event.content.parts))
                reply = next((value for value in reversed(texts) if value), "")
                responses.append({"app": app, "prompt": prompt, "reply": reply})
                if not reply:
                    raise AssertionError("No final reply")
                return reply

            async def read(case, app, prompt):
                return await checked_read_only(case, lambda: ask(app, prompt), http, db_checks)

            reply = await read("read_via_real_mcp", "quotation_agent", "查詢報價單 QT-20260330-001")
            assert "QT-20260330-001" in reply and "http://localhost:53000/quotations/" in reply
            records.append({"case": "read_via_real_mcp", "passed": True})
            if not skip_ambiguity:
                reply = await read("ambiguous_target_does_not_write", "quotation_agent",
                                   "QT-20260330-001 是舊單；請把 QT-20260325-001 轉訂單")
                assert "請" in reply and "報價單" in reply and "訂單編號:" not in reply
                records.append({"case": "ambiguous_target_does_not_write", "passed": True})
            reply = await read("grounded_policy", "pricing_advisor", "毛利率要多少以上業務才能自己改價？")
            assert "25% 以上，業務可直接調整" in reply and "5% 以上、未滿 15%，需總經理核准" in reply and "OKF" in reply
            records.append({"case": "grounded_policy", "passed": True})
    except Exception as exc:
        records.append({"case": "incomplete", "passed": False, "error_type": type(exc).__name__})
        print(f"API smoke stopped without retry: {type(exc).__name__}", flush=True)
    finally:
        try:
            if Gemini is not None and original_generate is not None:
                Gemini.generate_content_async = original_generate
            for name, runner in runners.items():
                await close_safely(name, runner.close, cleanup_errors)
            if first is not None:
                # The workflow calls this toolset manually, so Runner cannot
                # discover it among declarative tools during Runner.close().
                await close_safely("quotation_mcp_toolset", first.mcp_toolset.close, cleanup_errors)
            if sdk_client is not None:
                await close_safely("gemini_async_client", sdk_client.aio.aclose, cleanup_errors)
                try:
                    sdk_client.close()
                except Exception as exc:
                    cleanup_errors.append({"resource": "gemini_sync_client", "error_type": type(exc).__name__})
            await close_safely("snapshot_client", http.aclose, cleanup_errors)
        finally:
            # Cleanup failure must never erase the paid-call or database evidence.
            complete = (len(records) == expected_cases and all(row["passed"] for row in records) and not cleanup_errors
                        and len(db_checks) == expected_cases and all(row.get("unchanged") for row in db_checks))
            report = {
                "selected_model": model, "complete": complete, "isolated_backend": BACKEND,
                "call_limit": budget.limit, "expected_cases": expected_cases, "model_call_count": len(calls),
                "generation_http_attempt_count": sum(row["kind"] == "generation" for row in budget.requests),
                "catalog_http_attempt_count": sum(row["kind"] == "catalog" for row in budget.requests),
                "configured_retry_attempts": 1, "automatic_continuation": False,
                "calls": calls, "http_attempts": budget.requests, "database_checks": db_checks,
                "results": records, "responses": responses, "cleanup_errors": cleanup_errors,
            }
            save_report(args.output, report)
            print(json.dumps({k: report[k] for k in ("selected_model", "complete", "model_call_count",
                                                       "generation_http_attempt_count", "results")}, ensure_ascii=False), flush=True)
    if not complete:
        raise SystemExit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--local-report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model", choices=["gemini-2.5-flash-lite", "gemini-3.1-flash-lite", "gemini-3.5-flash-lite"],
                        default="gemini-3.1-flash-lite", help="Cheapest Lite model this account can call; 2.5 Flash-Lite rejects new users")
    parser.add_argument("--generation-limit", type=int, choices=range(1, 5), default=4)
    parser.add_argument("--skip-ambiguity-case", action="store_true", help="Only query and policy; requires three generation attempts")
    asyncio.run(main(parser.parse_args()))
