"""依知識庫規則判斷改價與轉訂單；已作廢、已過期的規則不拿來判斷。"""

import pytest

from pricing_advisor.computation import run_price_change_impact
from pricing_advisor.okf import Bundle, parse_time
from pricing_advisor.policies import evaluate_order_conversion, evaluate_price_change


async def _decision(bundle, backend, number, target, now=None):
    receipt = await run_price_change_impact(bundle, backend, number, target)
    return evaluate_price_change(bundle, receipt["result"], now=now)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "target, expected",
    [(200000, "none"), (180000, "sales_manager"), (160000, "general_manager"), (150000, "forbidden"), (140000, "forbidden")],
)
async def test_margin_tiers(bundle_path, fake_backend, target, expected):
    decision = await _decision(Bundle(bundle_path), fake_backend, "QT-20260325-001", target)
    assert decision.approval == expected


@pytest.mark.asyncio
async def test_deprecated_and_stale_rules_are_skipped(bundle_path, fake_backend):
    decision = await _decision(Bundle(bundle_path), fake_backend, "QT-20260325-001", 180000)
    skipped = dict(decision.skipped)
    assert skipped["policies/discount-approval-2025"] == "已作廢"
    assert "過期" in skipped["policies/promo-2026q3"]
    assert {v.concept_id for v in decision.verdicts} == {"policies/discount-approval", "policies/pricing-factor-floor"}


@pytest.mark.asyncio
async def test_factor_floor_and_promo(bundle_path, fake_backend):
    bundle = Bundle(bundle_path)
    # 10 月：促銷已過期，new 下限 0.90，因子 0.8636 要主管核准（毛利率 34.87% 夠）
    october = await _decision(bundle, fake_backend, "QT-20260328-001", 76000)
    assert october.approval == "sales_manager"
    # 8 月：促銷還有效，下限暫時是 0.85
    august = await _decision(bundle, fake_backend, "QT-20260328-001", 76000, now=parse_time("2026-08-01T00:00:00Z"))
    assert august.approval == "none"


@pytest.mark.asyncio
async def test_threshold_is_not_passed_by_rounding(bundle_path, fake_backend):
    # 191333：毛利率實際 24.9998%，四捨五入顯示 25.00%，不能因此放行
    bundle = Bundle(bundle_path)
    receipt = await run_price_change_impact(bundle, fake_backend, "QT-20260325-001", 191333)
    assert receipt["result"]["new_margin"] == "0.2500"
    decision = evaluate_price_change(bundle, receipt["result"])
    assert decision.approval == "sales_manager"
    assert "判斷" in decision.verdicts[0].reason


@pytest.mark.asyncio
async def test_after_write_check_uses_exact_factor(bundle_path, fake_backend):
    bundle = Bundle(bundle_path)
    receipt = await run_price_change_impact(bundle, fake_backend, "QT-20260325-001", 200000)
    assert evaluate_price_change(bundle, {**receipt["result"], "current_factor": receipt["result"]["new_factor"], "current_total": receipt["result"]["new_total"], "current_margin": receipt["result"]["new_margin"]}, conservative=False).approval == "none"


def _set_frontmatter(path, old, new):
    text = path.read_text(encoding="utf-8")
    assert old in text
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


@pytest.mark.asyncio
async def test_missing_margin_rule_does_not_open_the_gate(bundle_copy, fake_backend):
    # 毛利率規則作廢後只剩報價因子下限；200000 原本可以直接改，現在要主管核准
    _set_frontmatter(bundle_copy / "policies" / "discount-approval.md", "status: stable", "status: deprecated")
    decision = await _decision(Bundle(bundle_copy), fake_backend, "QT-20260325-001", 200000)
    assert decision.approval == "sales_manager"
    assert any(v.concept_id == "missing:margin_tiers" for v in decision.verdicts)


@pytest.mark.asyncio
async def test_unknown_level_and_malformed_rule_fail_closed(bundle_copy, fake_backend):
    bundle = Bundle(bundle_copy)
    receipt = await run_price_change_impact(bundle, fake_backend, "QT-20260325-001", 200000)
    result = {**receipt["result"], "customer_level": "partner"}
    assert evaluate_price_change(bundle, result).approval == "sales_manager"

    _set_frontmatter(
        bundle_copy / "policies" / "discount-approval.md",
        "{ min_margin: 0.25, approval: none,",
        "{ min_margin: 0.25, approval: nobody,",
    )
    decision = await _decision(Bundle(bundle_copy), fake_backend, "QT-20260325-001", 200000)
    assert decision.approval == "forbidden"


def test_order_conversion_rules(bundle_path, snapshot):
    bundle = Bundle(bundle_path)
    quotations, orders = snapshot["quotations"], snapshot["orders_by_customer"]

    published = quotations["QT-20260301-001"]
    assert evaluate_order_conversion(bundle, published, orders[str(published["customer_id"])]).allowed

    draft = quotations["QT-20260325-001"]
    decision = evaluate_order_conversion(bundle, draft, [])
    assert not decision.allowed and "draft" in decision.reasons[0]

    converted = quotations["QT-20260115-001"]
    decision = evaluate_order_conversion(bundle, converted, orders[str(converted["customer_id"])])
    assert not decision.allowed and decision.existing_orders == ["ORD-20260118-001（completed）"]

    cancelled = [{**orders[str(converted["customer_id"])][0], "status": "cancelled"}]
    assert evaluate_order_conversion(bundle, converted, cancelled).allowed


def test_gate_uses_rounded_amounts_and_actual_factor():
    from decimal import Decimal
    from pricing_advisor.policies import gate_numbers
    result = {"list_total": "3", "cost_total": "2.26", "new_factor": "1.0050",
              "new_total": "3.03", "conservative_total": "3.00",
              "current_factor": "1.0050", "current_total": "3.03"}
    assert gate_numbers(result)[0] < Decimal("0.25")
    margin, low, factor = gate_numbers(result, conservative=False)
    assert margin == (Decimal("3.03") - Decimal("2.26")) / Decimal("3.03")
    assert low == factor == Decimal("1.0050")
