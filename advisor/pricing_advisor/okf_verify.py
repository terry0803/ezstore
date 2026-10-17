"""process:okf-verify：用程式對照原始碼與執行中的系統，確認 system/ 等事實條目還是對的。

每個檢查回傳 (通過與否, 說明清單)。通過的條目寫入 verified: { by: process:okf-verify, at: 現在 }；
沒通過就拿掉之前 process:okf-verify 的紀錄，不動 human: 的紀錄。
policies/ 是公司決策，程式驗證不了，要由人審核（okf sign）。
"""

from __future__ import annotations

import asyncio
import hashlib
import re
from collections.abc import Awaitable, Callable
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx

from .okf import Bundle

VERIFIER = "process:okf-verify"

Check = Callable[["VerifyContext", Any], Awaitable[tuple[bool, list[str]]]]


class VerifyContext:
    def __init__(self, bundle: Bundle, repo: Path, backend_api: str, mcp_url: str, quotation_agent_url: str):
        self.bundle = bundle
        self.repo = repo
        self.backend_api = backend_api.rstrip("/")
        self.mcp_url = mcp_url
        self.quotation_agent_url = quotation_agent_url.rstrip("/")
        self._cache: dict[str, Any] = {}

    def source(self, rel: str) -> str:
        return (self.repo / rel).read_text(encoding="utf-8")

    async def get(self, path: str, **params: Any) -> Any:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(f"{self.backend_api}{path}", params=params or None)
            response.raise_for_status()
            return response.json()

    async def quotations(self) -> list[dict]:
        if "quotations" not in self._cache:
            data = await self.get("/quotations", page_size=100)
            self._cache["quotations"] = data.get("data") or []
        return self._cache["quotations"]

    async def quotation(self, number: str) -> dict:
        found = await self.get("/quotations", quotation_number=number, page_size=1)
        return await self.get(f"/quotations/{found['data'][0]['id']}")


def _d(value: Any) -> Decimal:
    return Decimal(str(value))


def _recompute(q: dict) -> tuple[Decimal, Decimal, Decimal, Decimal]:
    items = q.get("items") or []
    total = sum((_d(i["subtotal"]) for i in items), Decimal(0))
    cost = sum((_d(i["product_cost"]) * i["quantity"] for i in items), Decimal(0))
    listed = sum((_d(i["list_price"]) * i["quantity"] for i in items), Decimal(0))
    profit = sum(((_d(i["unit_price"]) - _d(i["product_cost"])) * i["quantity"] for i in items), Decimal(0))
    return total, cost, listed, profit


async def check_customer_levels(ctx: VerifyContext, concept) -> tuple[bool, list[str]]:
    notes, ok = [], True
    expected = {k: _d(v) for k, v in (concept.frontmatter.get("default_pricing_factor") or {}).items()}
    code = ctx.source("backend/models/customer.go")
    in_code = {m[0]: _d(m[1]) for m in re.findall(r'case "(\w+)":\s*return decimal\.NewFromFloat\(([\d.]+)\)', code)}
    for level, value in expected.items():
        api = _d((await ctx.get(f"/pricing-factor/{level}"))["pricing_factor"])
        same = in_code.get(level) == value == api
        ok &= same
        notes.append(f"{level}：條目 {value}、原始碼 {in_code.get(level)}、API {api}{'' if same else ' ✗'}")
    return ok, notes


async def check_pricing_formula(ctx: VerifyContext, concept) -> tuple[bool, list[str]]:
    code = ctx.source("backend/services/quotation_service.go")
    needles = [
        "product.ListPrice.Mul(pricingFactor)",
        "unitPrice.Mul(quantity)",
        "totalPrice.Add(item.Subtotal)",
        "item.UnitPrice.Sub(item.ProductCost).Mul(",
        "profitAmount.Div(totalPrice)",
        "已發佈的報價單不可修改",
        "已發佈的報價單不可刪除",
    ]
    missing = [n for n in needles if n not in code]
    notes = [f"原始碼找到 {len(needles) - len(missing)}/{len(needles)} 段公式與規則"]
    notes += [f"原始碼找不到：{n} ✗" for n in missing]
    bad = 0
    for q in await ctx.quotations():
        factor = _d(q["pricing_factor"])
        for item in q.get("items") or []:
            if abs(_d(item["unit_price"]) - _d(item["list_price"]) * factor) > Decimal("0.005"):
                bad += 1
            if abs(_d(item["subtotal"]) - _d(item["unit_price"]) * item["quantity"]) > Decimal("0.01"):
                bad += 1
    notes.append(f"API 的品項單價與小計和公式不符：{bad} 筆")
    return not missing and bad == 0, notes


async def check_quotations_table(ctx: VerifyContext, concept) -> tuple[bool, list[str]]:
    code = ctx.source("backend/models/quotation.go")
    columns = [
        "quotation_number", "customer_id", "customer_level", "pricing_factor", "total_price",
        "profit_amount", "profit_rate", "status", "notes", "product_cost", "list_price",
        "unit_price", "quantity", "subtotal",
    ]
    missing = [c for c in columns if f'json:"{c}"' not in code]
    notes = [f"models/quotation.go 欄位 {len(columns) - len(missing)}/{len(columns)}"]
    ok = not missing and "decimal(5,4)" in code and "default:'draft'" in code
    total_bad, profit_bad = set(), set()
    for q in await ctx.quotations():
        if q["quotation_number"] < "QT-2026" or q["quotation_number"] > "QT-20260331-999":
            continue  # 只比對測試資料的 12 張
        total, _, _, profit = _recompute(q)
        if total != _d(q["total_price"]):
            total_bad.add(q["quotation_number"])
        if profit != _d(q["profit_amount"]):
            profit_bad.add(q["quotation_number"])
    stated_total = {"QT-20260115-001"}
    stated_profit = {
        "QT-20260115-001", "QT-20260120-001", "QT-20260210-001", "QT-20260218-001",
        "QT-20260325-001", "QT-20260326-001", "QT-20260328-001",
    }
    notes.append(f"總價不一致：{sorted(total_bad)}")
    notes.append(f"利潤不一致：{len(profit_bad)} 張")
    same = total_bad == stated_total and profit_bad == stated_profit
    if not same:
        notes.append("和條目寫的不一致清單不同 ✗（測試資料可能沒有重灌）")
    return ok and same, notes


async def check_orders_table(ctx: VerifyContext, concept) -> tuple[bool, list[str]]:
    code = ctx.source("backend/models/order.go")
    ok = all(f'json:"{c}"' in code for c in ("order_number", "customer_id", "quotation_id", "total_price", "status"))
    ok &= "default:'pending'" in code
    seed = ctx.source("scripts/seed-test-data.sql")
    rows = re.findall(r"\(\d+, '[^']*', '[^']*', '(ORD-\d{8}-\d{3})', \d+, (\d+|NULL), [\d.]+, '(\w+)'", seed)
    numbers = {i + 1: n for i, n in enumerate(re.findall(r"'(QT-\d{8}-\d{3})', \d+, '\w+', [\d.]+", seed))}
    linked = {numbers[int(q)]: (o, s) for o, q, s in rows if q != "NULL"}
    for line in concept.body.splitlines():
        match = re.match(r"\| (QT-\d{8}-\d{3}) \| (ORD-\d{8}-\d{3}) \| (\w+) \|", line)
        if match:
            ok &= linked.get(match.group(1)) == (match.group(2), match.group(3))
    stated = len(re.findall(r"^\| QT-", concept.body, re.M))
    return ok and stated == len(linked), [f"seed 有 {len(rows)} 筆訂單，{len(linked)} 筆關聯報價單；條目列 {stated} 筆"]


async def check_backend_api(ctx: VerifyContext, concept) -> tuple[bool, list[str]]:
    routes = ctx.source("backend/routes/routes.go")
    needles = [
        'quotations.GET("", ', 'quotations.GET("/:id", ', 'quotations.PUT("/:id", ',
        'quotations.POST("/:id/duplicate", ', 'quotations.POST("/:id/publish", ',
        'quotations.DELETE("/:id", ', 'orders.GET("", ', 'orders.POST("", ',
        'customers.GET("", ', 'v1.GET("/pricing-factor/:level", ',
    ]
    missing = [n for n in needles if n not in routes]
    listed = await ctx.get("/quotations", page_size=1)
    keys_ok = {"data", "total", "page", "page_size"} <= set(listed)
    await ctx.get("/orders", customer_id=1, page_size=1)
    await ctx.get("/customers", search="史塔克", page_size=1)
    notes = [f"routes.go 找到 {len(needles) - len(missing)}/{len(needles)} 條路由", f"清單格式{'正確' if keys_ok else '不同 ✗'}"]
    return not missing and keys_ok, notes


async def check_mcp_tools(ctx: VerifyContext, concept) -> tuple[bool, list[str]]:
    from google.adk.tools.mcp_tool import McpToolset
    from google.adk.tools.mcp_tool.mcp_session_manager import StreamableHTTPConnectionParams

    toolset = McpToolset(connection_params=StreamableHTTPConnectionParams(url=ctx.mcp_url, timeout=20.0))
    try:
        names = sorted(t.name for t in await toolset.get_tools())
    finally:
        await toolset.close()
    expected = sorted(concept.frontmatter.get("mcp_tools") or [])
    code = ctx.source("mcp_server/server.py")
    bisect = concept.frontmatter.get("bisect") or {}
    code_ok = (
        f"BISECT_MAX_ITERATIONS = {bisect.get('max_iterations')}" in code
        and f"BISECT_LOW, BISECT_HIGH = {bisect.get('low')}, {bisect.get('high')}" in code
        and f"BISECT_TOLERANCE = {bisect.get('tolerance')}" in code
    )
    return names == expected and code_ok, [f"MCP 工具：{', '.join(names)}", f"二分法設定{'相符' if code_ok else '不符 ✗'}"]


async def check_quotation_agent(ctx: VerifyContext, concept) -> tuple[bool, list[str]]:
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.get(f"{ctx.quotation_agent_url}/.well-known/agent-card.json")
        response.raise_for_status()
        card = response.json()
    skills = {s["id"]: s for s in card.get("skills", [])}
    expected = concept.frontmatter.get("a2a_skills") or []
    ok = card.get("name") == "quotation_agent" and sorted(skills) == sorted(expected)
    examples_ok = all(any(e in concept.body for e in skills[s].get("examples", [])) for s in expected if s in skills)
    return ok and examples_ok, [f"agent card：{card.get('name')}，skill {len(skills)} 個，例句{'相符' if examples_ok else '不符 ✗'}"]


async def check_price_change_impact(ctx: VerifyContext, concept) -> tuple[bool, list[str]]:
    from .computation import _load_function

    fm = concept.frontmatter
    path = ctx.bundle.resolve_path(str(fm["computation"]), concept)
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if fm.get("computation_sha256") != actual:
        return False, ["計算程式和登記的 computation_sha256 不同 ✗（要先由人審核再重新登記）"]
    attester = ctx.bundle.resolve_path(str((fm.get("attester") or {}).get("resource")), concept)
    if fm.get("attester_sha256") != hashlib.sha256(attester.read_bytes()).hexdigest():
        return False, ["驗證程式和登記的 attester_sha256 不同 ✗（要先由人審核再重新登記）"]
    compute = _load_function(path, "compute")
    bad = []
    for q in await ctx.quotations():
        detail = await ctx.get(f"/quotations/{q['id']}")
        total, cost, listed, profit = _recompute(detail)
        result = compute(detail, float(total))
        if _d(result["new_factor"]) != _d(detail["pricing_factor"]).quantize(Decimal("0.0001")):
            bad.append(detail["quotation_number"])
        elif _d(result["new_profit"]) != profit.quantize(Decimal("0.01")):
            bad.append(detail["quotation_number"])
    return not bad, [f"用 {len(await ctx.quotations())} 張報價單的目前總價反推，報價因子與利潤不符：{bad or '無'}"]


async def check_glossary_examples(ctx: VerifyContext, concept) -> tuple[bool, list[str]]:
    from .computation import _load_function

    if concept.id == "glossary/pricing-factor":
        q = await ctx.quotation("QT-20260330-001")
        item = q["items"][0]
        ok = _d(q["pricing_factor"]) == Decimal("0.95") and _d(item["list_price"]) == 650 and _d(item["unit_price"]) == Decimal("617.5")
        return ok, [f"QT-20260330-001 因子 {q['pricing_factor']}、定價 {item['list_price']}、單價 {item['unit_price']}"]
    q = await ctx.quotation("QT-20260325-001")
    computation = ctx.bundle.get("computations/price-change-impact")
    compute = _load_function(ctx.bundle.resolve_path(str(computation.frontmatter["computation"]), computation), "compute")
    result = compute(q, 180000)
    total, cost, _, profit = _recompute(q)
    ok = (total, cost, profit) == (Decimal(211560), Decimal(143500), Decimal(68060))
    ok &= result["new_profit"] == "36506.60" and result["new_margin"] == "0.2028"
    return ok, [f"QT-20260325-001 重算 總價 {total}、成本 {cost}、利潤 {profit}；壓到 180000 利潤 {result['new_profit']}、毛利率 {result['new_margin']}"]


CHECKS: dict[str, Check] = {
    "system/customer-levels": check_customer_levels,
    "system/pricing-formula": check_pricing_formula,
    "system/quotations-table": check_quotations_table,
    "system/orders-table": check_orders_table,
    "system/backend-api": check_backend_api,
    "system/mcp-tools": check_mcp_tools,
    "system/quotation-agent": check_quotation_agent,
    "computations/price-change-impact": check_price_change_impact,
    "glossary/pricing-factor": check_glossary_examples,
    "glossary/profit-rate": check_glossary_examples,
}


async def run_checks(ctx: VerifyContext, only: list[str] | None = None) -> dict[str, tuple[bool, list[str]]]:
    results = {}
    for concept_id, check in CHECKS.items():
        if only and concept_id not in only:
            continue
        concept = ctx.bundle.get(concept_id)
        if concept is None:
            results[concept_id] = (False, ["知識庫沒有這個條目"])
            continue
        try:
            results[concept_id] = await check(ctx, concept)
        except Exception as e:  # 連不到系統也算沒通過
            results[concept_id] = (False, [f"檢查失敗：{e.__class__.__name__}: {e}"])
    return results


def run(ctx: VerifyContext, only: list[str] | None = None) -> dict[str, tuple[bool, list[str]]]:
    return asyncio.run(run_checks(ctx, only))
