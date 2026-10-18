"""Offline regressions for the smoke harness; no actual server or model."""
import asyncio
import contextlib
import importlib.util
import io
import json
import socket
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import aiohttp
import httpx
import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "verify_gemini_smoke.py"
spec = importlib.util.spec_from_file_location("smoke_under_test", SCRIPT)
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)

@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    original_connect = socket.socket.connect

    def blocked(*args, **kwargs):
        raise AssertionError("Unexpected real network access")

    def guarded_connect(sock, address):
        # Windows asyncio uses the standard-library socketpair internally.
        if getattr(socket.socketpair, "__code__", None) is sys._getframe(1).f_code:
            return original_connect(sock, address)
        return blocked()

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)
    monkeypatch.setattr(socket, "getaddrinfo", blocked)


class SnapshotTests(unittest.IsolatedAsyncioTestCase):
    async def test_full_pagination_and_item_details(self):
        requests = []
        def respond(request):
            requests.append(str(request.url))
            path = request.url.path
            if path.endswith("/orders"):
                return httpx.Response(200, json={"total": 0, "data": []})
            if path.endswith("/quotations"):
                page = int(request.url.params["page"])
                ids = list(range(1, 101)) if page == 1 else [101]
                return httpx.Response(200, json={"total": 101, "data": [{"id": i} for i in ids]})
            record_id = int(path.rsplit("/", 1)[-1])
            return httpx.Response(200, json={"id": record_id, "total_price": 123,
                                            "items": [{"id": 2, "quantity": 1}, {"id": 1, "quantity": 3}]})
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
            value = await smoke.snapshot_backend(http)
        self.assertEqual(101, len(value["quotes"]))
        self.assertEqual([1, 2], [x["id"] for x in value["quotes"]["101"]["items"]])
        self.assertTrue(any("page=2" in url for url in requests))

    def test_same_counts_changed_item_is_not_read_only(self):
        before = {"quotes": {"1": {"id": 1, "items": [{"id": 7, "quantity": 1}]}}, "orders": {}}
        after = {"quotes": {"1": {"id": 1, "items": [{"id": 7, "quantity": 2}]}}, "orders": {}}
        result = smoke.snapshot_check("edit", before, after)
        self.assertFalse(result["unchanged"])
        self.assertEqual(result["counts_before"], result["counts_after"])
        self.assertEqual(["1"], result["changed_ids"]["quotes"])
        self.assertNotEqual(result["before_sha256"], result["after_sha256"])

    async def test_failed_ask_still_checks_and_reports_modified_db(self):
        values = [{"quotes": {}, "orders": {}}, {"quotes": {"1": {"id": 1}}, "orders": {}}]
        checks = []
        with patch.object(smoke, "snapshot_backend", AsyncMock(side_effect=values)):
            with self.assertRaisesRegex(AssertionError, "changed quotations"):
                await smoke.checked_read_only("failure", AsyncMock(side_effect=ValueError("bad model")), None, checks)
        self.assertFalse(checks[0]["unchanged"])

    async def test_after_snapshot_failure_is_not_a_successful_check(self):
        checks = []
        with patch.object(smoke, "snapshot_backend", AsyncMock(side_effect=[{"quotes": {}, "orders": {}}, ValueError("unavailable")])):
            with self.assertRaises(ValueError):
                await smoke.checked_read_only("unavailable", AsyncMock(return_value="ok"), None, checks)
        self.assertEqual([{"case": "unavailable", "checked": False, "error_type": "ValueError"}], checks)

    async def test_duplicate_page_rejected(self):
        def respond(request):
            if request.url.path.endswith("/quotations"):
                return httpx.Response(200, json={"total": 2, "data": [{"id": 1}]})
            return httpx.Response(200, json={"id": 1, "items": []})
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
            with self.assertRaisesRegex(RuntimeError, "Duplicate ID"):
                await smoke.snapshot_backend(http)


class BudgetTests(unittest.IsolatedAsyncioTestCase):
    async def test_http_attempts_capped_before_transport_without_key_in_report(self):
        actual = []
        original = httpx.AsyncClient.send
        budget = smoke.ApiBudget(4)
        budget.model = "gemini-test"
        def respond(request):
            actual.append(request)
            return httpx.Response(200, json={})
        with budget:
            async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
                for _ in range(4):
                    await client.post("https://generativelanguage.googleapis.com/v1beta/models/gemini-test:generateContent?key=secret-marker",
                                      headers={"x-goog-api-key": "secret-marker"}, json={"test": True})
                with self.assertRaises(smoke.RequestBudgetExceeded):
                    await client.post("https://generativelanguage.googleapis.com/v1beta/models/gemini-test:generateContent")
        self.assertIs(original, httpx.AsyncClient.send)
        self.assertEqual(4, len(actual))
        self.assertEqual(4, len(budget.requests))
        self.assertNotIn("secret-marker", json.dumps(budget.requests))

    async def test_redirect_not_followed(self):
        actual = []
        budget = smoke.ApiBudget()
        budget.model = "gemini-test"
        def respond(request):
            actual.append(request)
            return httpx.Response(307, headers={"Location": "https://elsewhere.invalid/leak"})
        with budget:
            async with httpx.AsyncClient(transport=httpx.MockTransport(respond), follow_redirects=True) as client:
                response = await client.post("https://generativelanguage.googleapis.com/v1beta/models/gemini-test:generateContent")
        self.assertEqual(307, response.status_code)
        self.assertEqual(1, len(actual))

    async def test_aiohttp_retries_and_failure_types_counted(self):
        actual = []
        async def fake_request(client, method, url, **kwargs):
            actual.append(kwargs)
            raise OSError("secret-marker")
        original = aiohttp.ClientSession._request
        with patch.object(aiohttp.ClientSession, "_request", fake_request):
            budget = smoke.ApiBudget(2)
            budget.model = "gemini-test"
            with budget:
                for _ in range(2):
                    with self.assertRaises(OSError):
                        await aiohttp.ClientSession._request(None, "POST", "https://generativelanguage.googleapis.com/v1beta/models/gemini-test:generateContent")
                with self.assertRaises(smoke.RequestBudgetExceeded):
                    await aiohttp.ClientSession._request(None, "POST", "https://generativelanguage.googleapis.com/v1beta/models/gemini-test:generateContent")
            self.assertIs(fake_request, aiohttp.ClientSession._request)
        self.assertIs(original, aiohttp.ClientSession._request)
        self.assertEqual(2, len(actual))
        self.assertTrue(all(row["allow_redirects"] is False for row in actual))
        self.assertTrue(all(row["error_type"] == "OSError" for row in budget.requests))
        self.assertNotIn("secret-marker", json.dumps(budget.requests))

    def test_sync_catalog_and_external_allowlist(self):
        budget = smoke.ApiBudget()
        with budget:
            with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json={}))) as client:
                client.get("https://generativelanguage.googleapis.com/v1beta/models?key=secret-marker")
                with self.assertRaises(RuntimeError):
                    client.get("https://unapproved.invalid/models")
                with self.assertRaises(RuntimeError):
                    client.post("https://generativelanguage.googleapis.com/v1beta/models/wrong:generateContent")
        self.assertEqual("catalog", budget.requests[0]["kind"])
        self.assertEqual(1, len(budget.requests))


class CleanupTests(unittest.IsolatedAsyncioTestCase):
    async def test_catalog_and_cleanup_errors_still_save_report_and_restore_http(self):
        from google import genai
        fake = types.SimpleNamespace(
            models=types.SimpleNamespace(list=lambda: (_ for _ in ()).throw(RuntimeError("secret-marker"))),
            aio=types.SimpleNamespace(aclose=AsyncMock(side_effect=RuntimeError("secret-marker"))),
            close=lambda: (_ for _ in ()).throw(RuntimeError("secret-marker")))
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            local = root / "local.json"
            output = root / "output.json"
            local.write_text(json.dumps({"model": "openai/test", "isolated_backend": smoke.BACKEND,
                                         "results": [{"case": case, "passed": True} for case in smoke.REQUIRED_LOCAL_CASES]}))
            original = httpx.AsyncClient.send
            with patch("dotenv.dotenv_values", return_value={"GEMINI_API_KEY": "fake-key"}), \
                 patch.dict("os.environ", {"GEMINI_API_KEY": "fake-key"}), \
                 patch.object(genai, "Client", return_value=fake), \
                 patch.object(smoke, "snapshot_backend", AsyncMock(return_value={"quotes": {}, "orders": {}})), \
                 contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaises(SystemExit):
                    await smoke.main(types.SimpleNamespace(local_report=local, output=output))
            report = json.loads(output.read_text(encoding="utf-8"))
            self.assertFalse(report["complete"])
            self.assertEqual(2, len(report["cleanup_errors"]))
            self.assertEqual(0, report["generation_http_attempt_count"])
            self.assertNotIn("secret-marker", output.read_text(encoding="utf-8"))
            self.assertNotIn("fake-key", output.read_text(encoding="utf-8"))
            self.assertIs(original, httpx.AsyncClient.send)

    async def test_missing_local_cases_stops_before_credentials_or_model(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "local.json"
            path.write_text(json.dumps({"results": []}))
            with patch("dotenv.dotenv_values", side_effect=AssertionError("Must not read credentials")):
                with self.assertRaises(SystemExit):
                    await smoke.main(types.SimpleNamespace(local_report=path, output=Path(folder) / "unused.json"))

    async def test_failed_or_wrong_stack_local_report_cannot_reach_api(self):
        valid = {"model": "openai/test", "isolated_backend": smoke.BACKEND,
                 "results": [{"case": case, "passed": True} for case in sorted(smoke.REQUIRED_LOCAL_CASES)]}
        for defect in ("failed_case", "missing_case", "wrong_backend", "not_local_model"):
            with self.subTest(defect=defect), tempfile.TemporaryDirectory() as folder:
                report = json.loads(json.dumps(valid))
                if defect == "failed_case":
                    report["results"][0]["passed"] = False
                elif defect == "missing_case":
                    report["results"].pop()
                elif defect == "wrong_backend":
                    report["isolated_backend"] = "http://localhost:8080/api/v1"
                else:
                    report["model"] = "gemini-test"
                path = Path(folder) / "local.json"
                path.write_text(json.dumps(report), encoding="utf-8")
                with patch("dotenv.dotenv_values", side_effect=AssertionError("Must not read credentials")), \
                     patch("google.genai.Client", side_effect=AssertionError("Must not create API client")) as client:
                    with self.assertRaises(SystemExit):
                        await smoke.main(types.SimpleNamespace(local_report=path, output=Path(folder) / "unused.json"))
                    client.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
