"""Attested Computation：試算結果、收據、attester 的五項檢查、程式被改過時不執行。"""

import copy

import pytest

from pricing_advisor.computation import ComputationError, attest_receipt, run_price_change_impact
from pricing_advisor.okf import Bundle


@pytest.mark.asyncio
async def test_price_change_impact_numbers(bundle_path, fake_backend):
    bundle = Bundle(bundle_path)
    receipt = await run_price_change_impact(bundle, fake_backend, "QT-20260325-001", 180000)
    result = receipt["result"]
    assert result["list_total"] == "258000.00"
    assert result["cost_total"] == "143500.00"
    assert result["current_margin"] == "0.3217"
    assert result["new_factor"] == "0.6977"
    assert result["new_total"] == "180006.60"
    assert result["new_margin"] == "0.2028"
    assert result["stored_mismatch"] == ["profit_amount"]
    assert set(receipt) == {
        "computation", "computation_sha256", "source_url", "source_sha256",
        "source", "parameters", "result", "executed_at",
    }
    assert attest_receipt(bundle, receipt, claimed={"new_margin": "0.2028"})["ok"]


@pytest.mark.asyncio
async def test_unreachable_target(bundle_path, fake_backend):
    receipt = await run_price_change_impact(Bundle(bundle_path), fake_backend, "QT-20260330-001", 100000)
    result = receipt["result"]
    assert result["reachable"] is False
    assert result["max_total"] == "32500.00"


@pytest.mark.asyncio
async def test_attester_rejects_tampered_receipts(bundle_path, fake_backend):
    bundle = Bundle(bundle_path)
    receipt = await run_price_change_impact(bundle, fake_backend, "QT-20260325-001", 180000)

    changed_result = copy.deepcopy(receipt)
    changed_result["result"]["new_margin"] = "0.3000"
    assert "重算" in attest_receipt(bundle, changed_result)["reason"]

    changed_source = copy.deepcopy(receipt)
    changed_source["source"]["items"][0]["product_cost"] = "1.00"
    assert "source_sha256" in attest_receipt(bundle, changed_source)["reason"]

    wrong_code = copy.deepcopy(receipt)
    wrong_code["computation_sha256"] = "0" * 64
    assert "不是條目指定" in attest_receipt(bundle, wrong_code)["reason"]

    extra_param = copy.deepcopy(receipt)
    extra_param["parameters"]["discount"] = 0.1
    assert "沒宣告" in attest_receipt(bundle, extra_param)["reason"]

    verdict = attest_receipt(bundle, receipt, claimed={"new_margin": "0.3500"})
    assert not verdict["ok"] and "顯示" in verdict["reason"]


@pytest.mark.asyncio
async def test_modified_computation_is_not_executed(bundle_copy, fake_backend):
    code = bundle_copy / "references" / "computations" / "price_change_impact.py"
    code.write_text(code.read_text(encoding="utf-8").replace('FACTOR_MAX = Decimal("5.0")', 'FACTOR_MAX = Decimal("9.0")'), encoding="utf-8")
    bundle = Bundle(bundle_copy)
    with pytest.raises(ComputationError, match="computation_sha256"):
        await run_price_change_impact(bundle, fake_backend, "QT-20260325-001", 180000)


@pytest.mark.asyncio
async def test_parameters_are_checked(bundle_path, fake_backend):
    bundle = Bundle(bundle_path)
    with pytest.raises(ComputationError, match="target_total"):
        await run_price_change_impact(bundle, fake_backend, "QT-20260325-001", "很多")
    with pytest.raises(ComputationError, match="找不到"):
        await run_price_change_impact(bundle, fake_backend, "QT-20990101-001", 1000)
