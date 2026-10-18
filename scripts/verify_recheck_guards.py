"""Regression acceptance on the isolated ports, using the configured Gemini model.

Uses the existing live acceptance client to preserve replies, usage, and full
database comparisons. No production endpoint is configurable in this runner.
"""
from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from verify_live_agents import Acceptance, BACKEND


async def run(output: Path, model: str, interval: float, *, resume: bool = False):
    test = Acceptance(output, set(), model, resume=resume, min_turn_interval=interval)
    agent, advisor = "quotation_agent", "pricing_advisor"

    async def advisor_race():
        # Fresh isolated-only published quote avoids changing the seed quote or
        # depending on whether the full acceptance already converted it.
        source = await test.quote("QT-20260301-001")
        response = await test.http.post(f"{BACKEND}/quotations/{source['id']}/duplicate")
        response.raise_for_status()
        fixture = response.json()
        response = await test.http.post(f"{BACKEND}/quotations/{fixture['id']}/publish")
        response.raise_for_status()
        quote = await test.quote(fixture["quotation_number"])
        before = await test.snapshot()
        sessions = await asyncio.gather(test.session(advisor), test.session(advisor))
        prompt = f"幫我把 {quote['quotation_number']} 轉成訂單"
        replies = await asyncio.gather(*(test.ask(advisor, prompt, session) for session in sessions))
        after = await test.snapshot()
        new_ids = set(after["orders"]) - set(before["orders"])
        assert len(new_ids) == 1, replies
        assert after["quotes"] == before["quotes"], "Conversion changed a quotation"
        assert all(after["orders"].get(key) == value for key, value in before["orders"].items())
        order = after["orders"][next(iter(new_ids))]
        assert order["quotation_id"] == quote["id"]
        assert order["customer_id"] == quote["customer_id"]
        assert float(order["total_price"]) == float(quote["total_price"])
        items = lambda record: sorted((i["product_id"], i["quantity"], float(i["unit_price"])) for i in record["items"])
        assert items(order) == items(quote)
        assert sum("改完後核對：後端查得到" in reply for reply in replies) == 1, replies
        assert sum("沒有轉訂單" in reply for reply in replies) == 1, replies
        test.checks.append({"type": "advisor_concurrent_conversion", "fixture": quote["quotation_number"],
                            "new_order_ids": sorted(new_ids), "new_orders": 1,
                            "original_records_unchanged": True, "items_verified": True})

    cases = [
        ("a_cancel_copy", lambda: test.no_write(agent, "不要複製報價單 QT-20260330-001", ["只能協助"])),
        ("a_explain_copy", lambda: test.no_write(agent, "教我如何複製報價單 QT-20260330-001", ["只能協助"])),
        ("a_cancel_conversion", lambda: test.no_write(agent, "先不要把報價單 QT-20260330-001 轉訂單", ["只能協助"])),
        ("a_preserve_original_copy", lambda: test.mutation("不要修改原單，請複製報價單 QT-20260330-001", "quotes", expected_factor=0.95)),
        ("b_concurrent_conversion", advisor_race),
    ]
    try:
        for name, callback in cases:
            await test.case(name, callback)
        test._save(complete=True, expected_cases=len(cases))
    finally:
        await test.http.aclose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--model", required=True)
    parser.add_argument("--min-turn-interval", type=float, default=13)
    parser.add_argument("--resume", action="store_true", help="Keep passed cases and retain failed attempt evidence")
    args = parser.parse_args()
    asyncio.run(run(args.output, args.model, args.min_turn_interval, resume=args.resume))
