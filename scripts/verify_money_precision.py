"""Money regression against the isolated test stack (58080/58010), never the main DB.

Run with advisor/.venv/Scripts/python.exe scripts/verify_money_precision.py --out PATH.
Creates synthetic customers, products, quotations and orders in the test database.
No language model or API key is needed.
"""
import argparse
import asyncio
import json
import re
import sys
import uuid
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

import httpx
from google.adk.tools.mcp_tool import McpToolset
from google.adk.tools.mcp_tool.mcp_session_manager import StreamableHTTPConnectionParams

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "advisor"))
from pricing_advisor.backend import Backend
from pricing_advisor.computation import attest_receipt, run_price_change_impact
from pricing_advisor.okf import Bundle

D = Decimal
CENT = D("0.01")
API = "http://127.0.0.1:58080/api/v1"


def check_money(q, quote=True):
    total = D(0)
    cost = D(0)
    for item in q["items"]:
        unit, subtotal = D(item["unit_price"]), D(item["subtotal"])
        assert unit * item["quantity"] == subtotal, item
        assert unit == unit.quantize(CENT), item
        total += subtotal
        if quote:
            expected = (D(item["list_price"]) * D(q["pricing_factor"])).quantize(CENT, ROUND_HALF_UP)
            assert unit == expected, item
            cost += D(item["product_cost"]) * item["quantity"]
    assert total == D(q["total_price"]), q
    if quote:
        assert total - cost == D(q["profit_amount"]), q


async def main(out):
    rows = []
    token = uuid.uuid4().hex[:10]
    async with httpx.AsyncClient(base_url=API, timeout=30, trust_env=False) as client:
        async def request(method, path, data=None):
            r = await client.request(method, path, json=data)
            r.raise_for_status()
            return r.json()

        customer = await request("POST", "/customers", {"name": "Money regression " + token, "tax_id": "88992233", "level": "standard"})
        products = []
        for price in ["650", "1", "0.01"]:
            products.append(await request("POST", "/products", {"product_number": token + "-" + price,
                "name": "Money regression " + price, "cost": "0", "list_price": price, "inventory": 10000}))
        cases = [(0, "0.3333", 3, "649.95"), (1, "1.0050", 3, "3.03"),
                 (2, "0.5000", 1000, "10.00"), (2, "0.3333", 1000, "0.00")]
        source = None
        bundle, backend = Bundle(ROOT / "knowledge/ezstore"), Backend(API)
        for index, factor, quantity, expected in cases:
            payload = {"customer_id": customer["id"], "pricing_factor": factor,
                "items": [{"product_id": products[index]["id"], "quantity": quantity}]}
            created = await request("POST", "/quotations", payload)
            for action in ["create", "update", "duplicate"]:
                if action == "update":
                    created = await request("PUT", f"/quotations/{created['id']}", payload)
                elif action == "duplicate":
                    created = await request("POST", f"/quotations/{created['id']}/duplicate")
                saved = await request("GET", f"/quotations/{created['id']}")
                check_money(saved)
                assert D(saved["total_price"]) == D(expected)
                rows.append({"test": action, "factor": factor, "total": saved["total_price"], "passed": True})
            if index == 0:
                source = saved
            if D(expected) > 0:
                receipt = await run_price_change_impact(bundle, backend, saved["quotation_number"], float(expected))
                assert attest_receipt(bundle, receipt)["ok"]
                assert receipt["result"]["stored_mismatch"] == []
                assert D(receipt["result"]["current_total"]) == D(expected)
                rows.append({"test": "advisor_attestation", "factor": factor, "passed": True})
        mixed = await request("POST", "/quotations", {"customer_id": customer["id"], "pricing_factor": "0.3333",
            "items": [{"product_id": p["id"], "quantity": n} for p, n in zip(products, [3, 3, 1000])]})
        check_money(await request("GET", f"/quotations/{mixed['id']}"))
        rows.append({"test": "multiple_lines", "passed": True})
        payload = {"customer_id": customer["id"], "items": [{"product_id": products[1]["id"], "quantity": 3, "unit_price": "1.005"}]}
        order = await request("POST", "/orders", payload)
        for action in ["create", "update"]:
            if action == "update":
                order = await request("PUT", f"/orders/{order['id']}", payload)
            saved = await request("GET", f"/orders/{order['id']}")
            check_money(saved, quote=False)
            assert D(saved["total_price"]) == D("3.03")
            rows.append({"test": "order_" + action, "passed": True})
        toolset = McpToolset(connection_params=StreamableHTTPConnectionParams(url="http://127.0.0.1:58010/mcp", timeout=30))
        try:
            tools = {t.name: t for t in await toolset.get_tools()}
            for name, args in [
                ("update_pricing_factor", {"new_pricing_factor": 0.3333}),
                ("adjust_total_price", {"target_total_price": 649.95}),
                ("convert_to_order", {}),
            ]:
                result = await tools[name].run_async(args={"quotation_number": source["quotation_number"], **args}, tool_context=None)
                assert not result.get("isError"), result
                body = "\n".join(c.get("text", "") for c in result.get("content", []))
                if name == "convert_to_order":
                    orders = await backend.customer_orders(customer["id"])
                    saved = next(o for o in orders if o.get("quotation_id") == source["id"])
                    check_money(saved, quote=False)
                    assert D(saved["total_price"]) == D("649.95")
                else:
                    number = re.search(r"新報價單: (QT-\d+-\d+)", body).group(1)
                    saved = await backend.find_quotation(number)
                    check_money(saved)
                    assert abs(D(saved["total_price"]) - D("649.95")) < D("1")
                assert await request("GET", f"/quotations/{source['id']}") == source
                rows.append({"test": "mcp_" + name, "total": saved["total_price"], "original_unchanged": True, "passed": True})
        finally:
            await toolset.close()
    out.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"passed": len(rows), "total": len(rows), "model_calls": 0}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    asyncio.run(main(parser.parse_args().out))
