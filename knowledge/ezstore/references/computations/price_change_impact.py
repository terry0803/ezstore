"""改價影響試算：知識庫條目 computations/price-change-impact 指定的計算程式。

輸入是後端 GET /api/v1/quotations/{id} 回傳的報價單 JSON 與目標總價。只用標準函式庫，
不連網路也不讀檔。金額用 Decimal 計算，結果全部轉成字串，attester 才能逐字比對。
"""

from decimal import ROUND_HALF_UP, Decimal

# 和 MCP Server adjust_total_price 的二分法搜尋範圍相同
FACTOR_MIN = Decimal("0.01")
FACTOR_MAX = Decimal("5.0")

_CENT = Decimal("0.01")
_FACTOR = Decimal("0.0001")


def _d(value) -> Decimal:
    return Decimal(str(value))


def _money(value: Decimal) -> str:
    return str(value.quantize(_CENT, ROUND_HALF_UP))


def _rate(profit: Decimal, total: Decimal) -> str:
    if total == 0:
        return "0.0000"
    return str((profit / total).quantize(_FACTOR, ROUND_HALF_UP))


def _total(items: list, factor: Decimal) -> Decimal:
    # Match the stored unit price before multiplying by quantity.
    return sum(((_d(i["list_price"]) * factor).quantize(_CENT, ROUND_HALF_UP)
                * i["quantity"] for i in items), Decimal(0))


def compute(quotation: dict, target_total) -> dict:
    items = quotation.get("items") or []
    if not items:
        raise ValueError("報價單沒有品項，沒辦法試算")
    target = _d(target_total)
    if target <= 0:
        raise ValueError("目標總價必須大於 0")

    # L is used to estimate the factor; totals sum rounded unit prices × quantity.
    list_total = sum((_d(i["list_price"]) * i["quantity"] for i in items), Decimal(0))
    cost_total = sum((_d(i["product_cost"]) * i["quantity"] for i in items), Decimal(0))
    if list_total <= 0:
        raise ValueError("定價合計是 0，沒辦法試算")

    current_factor = _d(quotation["pricing_factor"])
    current_total = _total(items, current_factor)
    current_profit = current_total - cost_total

    # 後端的報價因子存到小數 4 位
    raw_factor = target / list_total
    reachable = FACTOR_MIN <= raw_factor <= FACTOR_MAX
    new_factor = min(max(raw_factor, FACTOR_MIN), FACTOR_MAX).quantize(_FACTOR, ROUND_HALF_UP)
    new_total = _total(items, new_factor)
    new_profit = new_total - cost_total

    # 測試資料有些報價單存的總價、利潤和品項重算不同，標出來
    stored_mismatch = []
    if _d(quotation.get("total_price", 0)).quantize(_CENT) != current_total.quantize(_CENT):
        stored_mismatch.append("total_price")
    if _d(quotation.get("profit_amount", 0)).quantize(_CENT) != current_profit.quantize(_CENT):
        stored_mismatch.append("profit_amount")

    return {
        "quotation_number": quotation["quotation_number"],
        "customer_level": quotation.get("customer_level", ""),
        "status": quotation.get("status", ""),
        "list_total": _money(list_total),
        "cost_total": _money(cost_total),
        "current_factor": str(current_factor.quantize(_FACTOR, ROUND_HALF_UP)),
        "current_total": _money(current_total),
        "current_profit": _money(current_profit),
        "current_margin": _rate(current_profit, current_total),
        "target_total": _money(target),
        "reachable": reachable,
        "new_factor": str(new_factor),
        "new_total": _money(new_total),
        "conservative_total": _money(_total(items, max(new_factor - _FACTOR, _FACTOR))),
        "new_profit": _money(new_profit),
        "new_margin": _rate(new_profit, new_total),
        "max_total": _money(_total(items, FACTOR_MAX)),
        "min_total": _money(_total(items, FACTOR_MIN)),
        "stored_mismatch": stored_mismatch,
    }
