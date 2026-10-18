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
    assert result["stored_mismatch"] == ["profit_amount"]  # 老師 seed 存的利潤是 66060，重算 68060
    assert set(receipt) == {
        "computation", "computation_sha256", "source_url", "source_sha256",
        "source", "parameters", "result", "executed_at",
    }
    assert attest_receipt(bundle, receipt, claimed={"new_margin": "0.2028"})["ok"]


@pytest.mark.asyncio
@pytest.mark.parametrize("pollution, expected", [
    ({"total_price": "211710"}, ["total_price"]),
    ({"profit_amount": "66060"}, ["profit_amount"]),
    ({"total_price": "211710", "profit_amount": "66060"}, ["total_price", "profit_amount"]),
])
async def test_polluted_snapshot_is_detected(bundle_path, fake_backend, pollution, expected):
    # Corrupt a private copy so the normal fixture stays consistent for other tests.
    original = await fake_backend.find_quotation("QT-20260325-001")
    fake_backend.quotations = copy.deepcopy(fake_backend.quotations)
    # 先把這張單的存值改成和品項一致，再只弄壞指定的欄位
    fake_backend.quotations["QT-20260325-001"].update(total_price="211560", profit_amount="68060")
    fake_backend.quotations["QT-20260325-001"].update(pollution)
    bundle = Bundle(bundle_path)
    receipt = await run_price_change_impact(bundle, fake_backend, "QT-20260325-001", 180000)
    result = receipt["result"]
    assert result["stored_mismatch"] == expected
    # Recalculation still uses the unchanged item snapshots, not corrupted totals.
    assert result["current_total"] == "211560.00"
    assert result["current_profit"] == "68060.00"
    assert result["current_margin"] == "0.3217"
    assert result["new_total"] == "180006.60"
    assert original["total_price"] == "211560"
    assert original["profit_amount"] == "66060"  # 共用的快照沒有被改到
    assert attest_receipt(bundle, receipt)["ok"]


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
async def test_removed_pin_is_refused(bundle_copy, fake_backend):
    concept = bundle_copy / "computations" / "price-change-impact.md"
    text = concept.read_text(encoding="utf-8")
    concept.write_text("\n".join(l for l in text.splitlines() if not l.startswith("computation_sha256:")) + "\n", encoding="utf-8")
    with pytest.raises(ComputationError, match="沒有登記 computation_sha256"):
        await run_price_change_impact(Bundle(bundle_copy), fake_backend, "QT-20260325-001", 180000)


@pytest.mark.asyncio
async def test_modified_attester_is_refused(bundle_copy, fake_backend):
    bundle = Bundle(bundle_copy)
    receipt = await run_price_change_impact(bundle, fake_backend, "QT-20260325-001", 180000)
    attester = bundle_copy / "references" / "attesters" / "recompute.py"
    attester.write_text(attester.read_text(encoding="utf-8") + "\n\ndef attest(**kwargs):\n    return {'ok': True}\n", encoding="utf-8")
    verdict = attest_receipt(Bundle(bundle_copy), receipt)
    assert not verdict["ok"] and "attester_sha256" in verdict["reason"]


@pytest.mark.asyncio
async def test_deprecated_or_stale_computation(bundle_copy, fake_backend, monkeypatch):
    from pricing_advisor.computation import stale_note

    assert stale_note(Bundle(bundle_copy)) is None
    monkeypatch.setenv("OKF_NOW", "2027-05-01T00:00:00Z")
    assert "已過期" in stale_note(Bundle(bundle_copy))

    concept = bundle_copy / "computations" / "price-change-impact.md"
    concept.write_text(concept.read_text(encoding="utf-8").replace("status: stable", "status: deprecated", 1), encoding="utf-8")
    with pytest.raises(ComputationError, match="已作廢"):
        await run_price_change_impact(Bundle(bundle_copy), fake_backend, "QT-20260325-001", 180000)


@pytest.mark.asyncio
async def test_parameters_are_checked(bundle_path, fake_backend):
    bundle = Bundle(bundle_path)
    with pytest.raises(ComputationError, match="target_total"):
        await run_price_change_impact(bundle, fake_backend, "QT-20260325-001", "很多")
    with pytest.raises(ComputationError, match="找不到"):
        await run_price_change_impact(bundle, fake_backend, "QT-20990101-001", 1000)


@pytest.mark.asyncio
@pytest.mark.parametrize('price,factor,quantity,total,target', [
    ('650','0.3333',3,'649.95',649.95),
    ('1','1.0050',3,'3.03',3.015),
    ('0.01','0.5000',1000,'10.00',5),
])
async def test_cent_rounding_matches_quote_and_attestation(bundle_path, fake_backend, price, factor, quantity, total, target):
    q=copy.deepcopy(await fake_backend.find_quotation('QT-20260330-001'))
    q.update(pricing_factor=factor,total_price=total,profit_amount=total)
    q['items']=[{'list_price':price,'product_cost':'0','quantity':quantity}]
    fake_backend.quotations={q['quotation_number']:q}
    bundle=Bundle(bundle_path)
    receipt=await run_price_change_impact(bundle,fake_backend,q['quotation_number'],target)
    assert receipt['result']['current_total']==total
    assert receipt['result']['new_total']==total
    assert receipt['result']['stored_mismatch']==[]
    assert attest_receipt(bundle,receipt)['ok']
