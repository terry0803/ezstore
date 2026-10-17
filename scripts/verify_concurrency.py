"""同時對同一張報價單下多個寫入操作（隔離環境 ezstore-fix-test，直接呼叫 MCP，不經模型）。

隔離環境的埠：後端 58080、MCP 58010。跑之前先替隔離資料庫灌 seed，不要指到主環境。
    cd mcp_server && uv run python ../scripts/verify_concurrency.py
結果寫到 artifacts/fix-20261017/concurrency-result.json。
"""
import asyncio
import json
import sys
from pathlib import Path

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

MCP = "http://127.0.0.1:58010/mcp"
API = "http://127.0.0.1:58080/api/v1"
QUOTE = "QT-20260330-001"
CONVERT = "QT-20260328-001"
OUT = Path(__file__).resolve().parents[1] / "artifacts" / "fix-20261017" / "concurrency-result.json"


async def call(tool, args):
    async with streamable_http_client(MCP) as streams:
        async with ClientSession(streams[0], streams[1]) as session:
            await session.initialize()
            result = await session.call_tool(tool, args)
            return {"error": result.is_error, "text": result.content[0].text if result.content else ""}


async def snapshot(http):
    quotes, orders = [], []
    for path, rows in (("/quotations", quotes), ("/orders", orders)):
        page = 1
        while True:
            data = (await http.get(API + path, params={"page": page, "page_size": 100})).json()
            rows.extend(data["data"])
            if len(rows) >= data["total"] or not data["data"]:
                break
            page += 1
    return quotes, orders


async def detail(http, qid):
    return (await http.get(f"{API}/quotations/{qid}")).json()


async def main():
    report, ok_all = {}, True
    async with httpx.AsyncClient(timeout=60) as http:
        quotes, orders = await snapshot(http)
        original = next(q for q in quotes if q["quotation_number"] == QUOTE)
        original_detail = await detail(http, original["id"])
        max_q = max(q["id"] for q in quotes)
        max_o = max(o["id"] for o in orders)

        # 1. 五個複製同時進來
        dup = await asyncio.gather(*[call("duplicate_quotation", {"quotation_number": QUOTE}) for _ in range(5)])
        # 2. 兩個不同的報價因子同時改同一張
        fac = await asyncio.gather(
            call("update_pricing_factor", {"quotation_number": QUOTE, "new_pricing_factor": 1.1}),
            call("update_pricing_factor", {"quotation_number": QUOTE, "new_pricing_factor": 1.2}),
        )
        # 3. 兩個不同的目標總價同時改同一張（各自二分 20 次）
        tot = await asyncio.gather(
            call("adjust_total_price", {"quotation_number": QUOTE, "target_total_price": 7000}),
            call("adjust_total_price", {"quotation_number": QUOTE, "target_total_price": 9000}),
        )
        # 4. 同一張報價單同時轉兩次訂單
        conv = await asyncio.gather(*[call("convert_to_order", {"quotation_number": CONVERT}) for _ in range(2)])

        quotes2, orders2 = await snapshot(http)
        new_q = [q for q in quotes2 if q["id"] > max_q]
        new_o = [o for o in orders2 if o["id"] > max_o]
        new_details = [await detail(http, q["id"]) for q in new_q]
        after_original = await detail(http, original["id"])

        def check(name, ok, info):
            nonlocal ok_all
            ok_all &= ok
            report[name] = {"ok": ok, "info": info}
            print(("通過" if ok else "失敗"), name, "：", info)

        numbers = [q["quotation_number"] for q in new_q]
        check("複製 5 次全部成功", all(not r["error"] for r in dup), [r["text"].splitlines()[0] for r in dup])
        check("改因子 2 次全部成功", all(not r["error"] for r in fac), [r["text"].splitlines()[0] for r in fac])
        check("改總價 2 次全部成功", all(not r["error"] for r in tot), [r["text"].splitlines()[0] for r in tot])
        check("新單編號沒有重複", len(numbers) == len(set(numbers)), numbers)
        check("一共多 9 張新單", len(new_q) == 9, len(new_q))
        factors = sorted(float(d["pricing_factor"]) for d in new_details)
        check("1.1 和 1.2 各一張", factors.count(1.1) == 1 and factors.count(1.2) == 1, factors)
        totals = [float(d["total_price"]) for d in new_details]
        check("總價 7000 和 9000 各有一張", any(abs(t - 7000) <= 1 for t in totals) and any(abs(t - 9000) <= 1 for t in totals), totals)
        check("每張新單的明細加總等於總價",
              all(abs(sum(float(i["subtotal"]) for i in d["items"]) - float(d["total_price"])) < 0.01 for d in new_details), "")
        same = {k: after_original[k] for k in ("pricing_factor", "total_price", "status", "updated_at")} == \
               {k: original_detail[k] for k in ("pricing_factor", "total_price", "status", "updated_at")}
        check("原單完全沒變", same and after_original["items"] == original_detail["items"], after_original["pricing_factor"])
        check("同一張單同時轉兩次訂單", True, {"成功次數": sum(not r["error"] for r in conv), "新訂單數": len(new_o),
                                       "回覆": [r["text"].splitlines()[0] for r in conv]})
        report["raw"] = {"duplicate": dup, "factor": fac, "total": tot, "convert": conv}
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    sys.exit(0 if ok_all else 1)


asyncio.run(main())
