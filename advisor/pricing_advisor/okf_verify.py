"""process:okf-verify：用程式對照原始碼與執行中的系統，確認 system/ 等事實條目還是對的。

每個檢查回傳 (通過與否, 說明清單)。通過的條目寫入 verified: { by: process:okf-verify, at: 現在 }；
沒通過就拿掉之前 process:okf-verify 的紀錄，不動 human: 的紀錄。
policies/ 是公司決策，程式驗證不了，要由人審核（okf sign）。
"""

from __future__ import annotations

import asyncio
import logging
import warnings
import hashlib
import re
from collections.abc import Awaitable, Callable
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any

import httpx

from .okf import Bundle

VERIFIER = "process:okf-verify"

DEMO_QUOTATIONS = frozenset({
    "QT-20260115-001", "QT-20260120-001", "QT-20260205-001", "QT-20260210-001",
    "QT-20260218-001", "QT-20260301-001", "QT-20260305-001", "QT-20260310-001",
    "QT-20260325-001", "QT-20260326-001", "QT-20260328-001", "QT-20260330-001",
})

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
            rows, seen = [], set()
            page, expected_total = 1, None
            while True:
                data = await self.get("/quotations", page=page, page_size=100)
                if not isinstance(data, dict) or not isinstance(data.get("data"), list):
                    raise ValueError("報價單分頁格式不完整")
                total = data.get("total")
                if type(total) is not int or total < 0 or data.get("page", page) != page:
                    raise ValueError("報價單分頁總筆數或頁碼不合法")
                if expected_total is None:
                    expected_total = total
                elif total != expected_total:
                    raise ValueError("分頁讀取時報價單總筆數改變，請重新驗證")
                batch = data["data"]
                for row in batch:
                    if not isinstance(row, dict) or type(row.get("id")) is not int or row["id"] in seen:
                        raise ValueError("報價單分頁缺少唯一 ID 或出現重複資料")
                    seen.add(row["id"])
                rows.extend(batch)
                if len(rows) == expected_total:
                    break
                if not batch or len(rows) > expected_total:
                    raise ValueError("報價單分頁未取得宣告的完整資料")
                page += 1
            # Do not cache a partial result if any page failed validation.
            self._cache["quotations"] = rows
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
        "product.ListPrice.Mul(pricingFactor).Round(2)",
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
            expected_unit = (_d(item["list_price"]) * factor).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            if _d(item["unit_price"]) != expected_unit:
                bad += 1
            if _d(item["subtotal"]) != _d(item["unit_price"]) * item["quantity"]:
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
    # 老師的 seed 有幾張單存的總價、利潤、利潤率和品項重算不同。條目把這些單列在
    # seed_mismatches，實際資料要和清單完全一致：多了代表資料被改壞，少了代表條目過時。
    stated = concept.frontmatter.get("seed_mismatches")
    fields = ("total_price", "profit_amount", "profit_rate")
    if not isinstance(stated, dict) or not all(isinstance(stated.get(f), list) for f in fields):
        return False, notes + ["條目沒有寫出 seed_mismatches（total_price、profit_amount、profit_rate 三份清單）✗"]
    total_bad, profit_bad, rate_bad, invalid = set(), set(), set(), set()
    seen, duplicate = set(), set()
    for q in await ctx.quotations():
        number = q.get("quotation_number")
        if number not in DEMO_QUOTATIONS:
            continue
        if number in seen:
            duplicate.add(number)
        seen.add(number)
        try:
            items = q.get("items")
            if not isinstance(items, list) or not items:
                raise ValueError("缺少完整品項")
            numeric = [_d(q[field]) for field in ("pricing_factor", "total_price", "profit_amount", "profit_rate")]
            numeric += [_d(item[field]) for item in items for field in ("list_price", "product_cost", "unit_price", "quantity", "subtotal")]
            if not all(value.is_finite() for value in numeric):
                raise ValueError("數值不是有限數")
            total, _, _, profit = _recompute(q)
            total = total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            profit = profit.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            rate = (profit / total).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP) if total else Decimal("0.0000")
            if total != _d(q["total_price"]):
                total_bad.add(number)
            if profit != _d(q["profit_amount"]):
                profit_bad.add(number)
            if rate != _d(q["profit_rate"]):
                rate_bad.add(number)
        except (ArithmeticError, ValueError, TypeError, KeyError):
            invalid.add(number)
    missing_quotes = DEMO_QUOTATIONS - seen
    notes.append(f"種子報價單完整覆蓋：{len(seen)}/{len(DEMO_QUOTATIONS)}")
    notes.append(f"總價不一致：{sorted(total_bad)}")
    notes.append(f"利潤不一致：{sorted(profit_bad)}")
    notes.append(f"利潤率不一致（ROUND_HALF_UP，小數 4 位）：{sorted(rate_bad)}")
    if missing_quotes or duplicate or invalid:
        notes.append(f"缺少：{sorted(missing_quotes)}；重複：{sorted(duplicate)}；無法重算：{sorted(invalid)} ✗")
    same = (total_bad == set(stated["total_price"]) and profit_bad == set(stated["profit_amount"])
            and rate_bad == set(stated["profit_rate"]))
    if not same:
        notes.append("和條目 seed_mismatches 寫的不一致清單不同 ✗（測試資料可能沒有重灌，或條目過時）")
    return ok and same and not any((missing_quotes, duplicate, invalid)), notes


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
    # ADK 的 MCP 工具會印實驗功能警告和「沒有 Google 預設憑證、不設 mTLS」的訊息，跟這裡的檢查無關，先關掉
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        logging.disable(logging.WARNING)
        from google.adk.tools.mcp_tool import McpToolset
        from google.adk.tools.mcp_tool.mcp_session_manager import StreamableHTTPConnectionParams

        toolset = McpToolset(connection_params=StreamableHTTPConnectionParams(url=ctx.mcp_url, timeout=20.0))
        try:
            names = sorted(t.name for t in await toolset.get_tools())
        finally:
            await toolset.close()
            logging.disable(logging.NOTSET)
    expected = sorted(concept.frontmatter.get("mcp_tools") or [])
    code = ctx.source("mcp_server/server.py")
    bisect = concept.frontmatter.get("bisect") or {}
    code_ok = (
        f"BISECT_MAX_ITERATIONS = {bisect.get('max_iterations')}" in code
        and f"BISECT_LOW, BISECT_HIGH = {bisect.get('low')}, {bisect.get('high')}" in code
        and f"BISECT_TOLERANCE = {bisect.get('tolerance')}" in code
    )
    notes = [f"MCP 工具：{', '.join(names)}", f"二分法設定{'相符' if code_ok else '不符 ✗'}"]
    # 只有條目寫了上限才比對，也才印出比對結果；沒寫就不宣稱上限相符
    limit = concept.frontmatter.get("max_pricing_factor")
    if limit is not None:
        limit_ok = f'<= Decimal("{limit}")' in code
        notes.append(f"報價因子上限 {limit} {'相符' if limit_ok else '不符 ✗'}")
        code_ok = code_ok and limit_ok
    return names == expected and code_ok, notes


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
    checked = 0
    skipped_zero = 0
    for q in await ctx.quotations():
        detail = await ctx.get(f"/quotations/{q['id']}")
        total, cost, listed, profit = _recompute(detail)
        # Zero totals are valid backend data, but are not valid target prices.
        if total == 0:
            skipped_zero += 1
            continue
        checked += 1
        result = compute(detail, float(total))
        # Cent rounding makes factor -> total many-to-one: a total cannot
        # uniquely recover the original factor. Check amounts independently.
        factor = _d(result["new_factor"])
        expected_total = sum(((_d(i["list_price"]) * factor).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                              * i["quantity"] for i in detail['items']), Decimal(0))
        if _d(result["current_total"]) != total or _d(result["current_profit"]) != profit:
            bad.append(detail["quotation_number"])
        elif _d(result["new_total"]) != expected_total or _d(result["new_profit"]) != expected_total - cost:
            bad.append(detail["quotation_number"])
    return not bad, [f"用 {checked} 張報價單核對逐項捨入後的目前與試算金額，不符：{bad or '無'}；總價為 0 跳過 {skipped_zero} 張（不適用正目標總價試算）"]


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
    ok &= result["new_profit"] == "36480.80" and result["new_margin"] == "0.2027"
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
