"""Live Gemini probes for cancellation and ambiguity findings on the isolated stack."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))

from verify_live_agents import Acceptance, BACKEND  # noqa: E402


OUTPUT = Path(__file__).with_name("live-edge-probes.json")
MODEL = "gemini-3.1-flash-lite"


def changes(before, after):
    result = {}
    for kind in ("quotes", "orders"):
        old, new = before[kind], after[kind]
        result[kind] = {
            "created_ids": sorted(set(new) - set(old)),
            "deleted_ids": sorted(set(old) - set(new)),
            "changed_existing_ids": sorted(key for key in set(old) & set(new) if old[key] != new[key]),
        }
    return result


async def main():
    test = Acceptance(OUTPUT, set(), MODEL, min_turn_interval=15)
    probes = []

    async def run(name, app, prompts, expected):
        session = await test.session(app)
        before = await test.snapshot()
        replies = []
        error = None
        try:
            for prompt in prompts:
                replies.append(await test.ask(app, prompt, session))
        except Exception as exc:  # preserve later probes and evidence
            error = type(exc).__name__
        after = await test.snapshot()
        probes.append({
            "name": name,
            "app": app,
            "prompts": prompts,
            "expected": expected,
            "replies": replies,
            "error_type": error,
            "changes": changes(before, after),
        })

    try:
        await run("advisor_cancel_copy", "pricing_advisor", ["不要複製報價單 QT-20260330-001"], "no write")
        await run("advisor_explain_copy", "pricing_advisor", ["教我如何複製報價單 QT-20260330-001"], "no write")
        await run(
            "advisor_ambiguous_price",
            "pricing_advisor",
            ["幫我把 QT-20260325-001 總價改成 200000 或 210000"],
            "clarify; no write",
        )
        await run(
            "first_agent_pending_cancel",
            "quotation_agent",
            ["請將總價改成8000", "先不要改了，QT-20260330-001"],
            "cancel pending request; no write",
        )
        await run(
            "advisor_cancel_after_check",
            "pricing_advisor",
            ["QT-20260325-001 壓到 200000 可以嗎？", "不要改了"],
            "cancel checked adjustment; no write",
        )
        await run(
            "advisor_preserve_original_copy",
            "pricing_advisor",
            ["不要修改原單，請複製報價單 QT-20260330-001"],
            "one new quote",
        )

        source = await test.quote("QT-20260301-001")
        response = await test.http.post(f"{BACKEND}/quotations/{source['id']}/duplicate")
        response.raise_for_status()
        fixture = response.json()
        response = await test.http.post(f"{BACKEND}/quotations/{fixture['id']}/publish")
        response.raise_for_status()
        await run(
            "advisor_cancel_conversion",
            "pricing_advisor",
            [f"不要把 {fixture['quotation_number']} 轉成訂單"],
            "no order",
        )
    finally:
        await test.http.aclose()

    usage = [
        event["usageMetadata"]
        for turn in test.turns
        for event in turn["events"]
        if event.get("usageMetadata")
    ]
    report = {
        "complete": True,
        "model": MODEL,
        "isolated_backend": BACKEND,
        "probe_count": len(probes),
        "turns": len(test.turns),
        "visible_model_events": len(usage),
        "total_tokens": sum(row.get("totalTokenCount", 0) for row in usage),
        "probes": probes,
    }
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("complete", "probe_count", "turns", "visible_model_events", "total_tokens")}, ensure_ascii=False))
    for row in probes:
        created = sum(len(value["created_ids"]) for value in row["changes"].values())
        changed = sum(len(value["changed_existing_ids"]) for value in row["changes"].values())
        print(json.dumps({"name": row["name"], "created": created, "changed": changed, "error": row["error_type"]}, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
