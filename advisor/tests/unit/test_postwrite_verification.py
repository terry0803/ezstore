"""A2A completion is accepted only after independent, complete backend checks."""
import copy
from decimal import Decimal, ROUND_HALF_UP
from types import SimpleNamespace

import pytest

from pricing_advisor import agent
from pricing_advisor.backend import BackendError
from tests.conftest import FakeBackend, SNAPSHOT

ORIGINAL = "QT-20260325-001"
NEW = "QT-20261017-001"
ORDER_SOURCE = "QT-20260301-001"
ORDER = "ORD-20261017-001"


def copied(quotation, *, refresh_price=False):
    fresh = copy.deepcopy(quotation)
    fresh.update(id=999, quotation_number=NEW)
    if refresh_price:
        fresh["items"][0]["list_price"] = str(Decimal(fresh["items"][0]["list_price"]) + 1000)
    list_total = sum(Decimal(row["list_price"]) * row["quantity"] for row in fresh["items"])
    factor = (Decimal("200000") / list_total).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    total = Decimal(0)
    for row in fresh["items"]:
        unit = (Decimal(row["list_price"]) * factor).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        row.update(unit_price=str(unit), subtotal=str(unit * row["quantity"]))
        total += unit * row["quantity"]
    cost = sum(Decimal(row["product_cost"]) * row["quantity"] for row in fresh["items"])
    fresh.update(pricing_factor=str(factor), total_price=str(total),
                 profit_amount=str(total - cost), profit_rate=str((total - cost) / total))
    return fresh


@pytest.fixture
def postwrite(monkeypatch):
    backend = FakeBackend(quotations=copy.deepcopy(SNAPSHOT["quotations"]),
                          orders=copy.deepcopy(SNAPSHOT["orders_by_customer"]))
    original = backend.quotations[ORIGINAL]
    backend.quotations[NEW] = copied(original)
    request = {"quotation_number": ORIGINAL, "target_total": 200000,
               "original_factor": original["pricing_factor"],
               "original_source_sha256": agent.sha256_hex(agent.canonical_json(original))}
    monkeypatch.setattr(agent, "backend", backend)
    return backend, request


@pytest.mark.asyncio
@pytest.mark.parametrize("refresh_price", [False, True])
async def test_quote_success_uses_actual_copy_prices_and_quantization(postwrite, refresh_price):
    backend, request = postwrite
    backend.quotations[NEW] = copied(backend.quotations[ORIGINAL], refresh_price=refresh_price)
    backend.quotations[NEW]["items"].reverse()  # Item order is not a semantic difference.
    reply = await agent._verify_after_write("apply_price", request, f"新報價單: {NEW}")
    assert "改完後核對（從後端重新讀" in reply
    assert "原單完整內容未變" in reply
    assert "總價符合指定目標" in reply
    assert "核對失敗" not in reply


@pytest.mark.asyncio
@pytest.mark.parametrize('round_unit_first', [False, True])
async def test_quote_requires_consistent_cent_rounding(postwrite, round_unit_first):
    backend, request = postwrite
    fresh = copied(backend.quotations[ORIGINAL])
    fresh["items"][2]["list_price"] = "9800.01"
    list_total = sum(Decimal(row["list_price"]) * row["quantity"] for row in fresh["items"])
    factor = (Decimal("200000") / list_total).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    total = Decimal(0)
    for row in fresh["items"]:
        exact_unit = Decimal(row["list_price"]) * factor
        if round_unit_first:
            exact_unit = exact_unit.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        exact_subtotal = exact_unit * row["quantity"]
        row.update(unit_price=str(exact_unit.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
                   subtotal=str(exact_subtotal.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)))
        total += exact_subtotal
    cost = sum(Decimal(row["product_cost"]) * row["quantity"] for row in fresh["items"])
    fresh.update(pricing_factor=str(factor), total_price=str(total.quantize(Decimal("0.01"))),
                 profit_amount=str((total - cost).quantize(Decimal("0.01"))))
    backend.quotations[NEW] = fresh
    reply = await agent._verify_after_write("apply_price", request, f"新報價單: {NEW}")
    if round_unit_first:
        assert "核對失敗" not in reply
        assert "總價符合指定目標" in reply
    else:
        assert "核對失敗" in reply


@pytest.mark.asyncio
@pytest.mark.parametrize("change", [
    "wrong_total", "same_id", "same_number", "other_customer", "changed_product",
    "changed_quantity", "missing_target", "nonfinite_total", "wrong_stored_profit",
    "source_notes", "source_item", "missing_source_hash", "missing_detail",
])
async def test_quote_false_success_is_rejected(postwrite, change):
    backend, request = postwrite
    fresh = backend.quotations[NEW]
    reply_number = NEW
    if change == "wrong_total":
        request["target_total"] = 205000
    elif change == "same_id":
        fresh["id"] = backend.quotations[ORIGINAL]["id"]
    elif change == "same_number":
        reply_number = ORIGINAL
    elif change == "other_customer":
        fresh["customer_id"] = 12345
    elif change == "changed_product":
        fresh["items"][0]["product_id"] = 12345
    elif change == "changed_quantity":
        fresh["items"][0]["quantity"] += 1
    elif change == "missing_target":
        del request["target_total"]
    elif change == "nonfinite_total":
        fresh["total_price"] = "NaN"
    elif change == "wrong_stored_profit":
        fresh["profit_amount"] = "1"
    elif change == "source_notes":
        backend.quotations[ORIGINAL]["notes"] += " edited"
    elif change == "source_item":
        backend.quotations[ORIGINAL]["items"][0]["product_name"] += " edited"
    elif change == "missing_source_hash":
        del request["original_source_sha256"]
    elif change == "missing_detail":
        del fresh["items"]
    reply = await agent._verify_after_write("apply_price", request, f"新報價單: {reply_number}")
    assert reply.startswith("改完後核對失敗：")
    assert "不能確認上方操作成功" in reply
    assert "原單完整內容未變" not in reply


@pytest.mark.asyncio
async def test_quote_duplicate_product_rows_are_not_collapsed(postwrite):
    backend, request = postwrite
    original = backend.quotations[ORIGINAL]
    original["items"].append(copy.deepcopy(original["items"][0]))
    request["original_source_sha256"] = agent.sha256_hex(agent.canonical_json(original))
    fresh = backend.quotations[NEW] = copied(original)
    fresh["items"].pop()  # The set of product IDs is unchanged, but one row is missing.
    reply = await agent._verify_after_write("apply_price", request, f"新報價單: {NEW}")
    assert "產品或數量與原單不同" in reply


@pytest.mark.asyncio
async def test_quote_ambiguous_receipt_does_not_select_first_number(postwrite):
    _, request = postwrite
    reply = await agent._verify_after_write("apply_price", request, f"新報價單: {NEW}\n新報價單: QT-20261017-002")
    assert "沒有唯一的新報價單編號" in reply


@pytest.mark.asyncio
async def test_quote_source_changed_during_verification_is_rejected(postwrite, monkeypatch):
    backend, request = postwrite
    find = backend.find_quotation
    original_reads = 0

    async def changed(number):
        nonlocal original_reads
        result = await find(number)
        if number == ORIGINAL:
            original_reads += 1
            if original_reads > 1:
                result["notes"] += " changed concurrently"
        return result

    monkeypatch.setattr(backend, "find_quotation", changed)
    reply = await agent._verify_after_write("apply_price", request, f"新報價單: {NEW}")
    assert "原報價單在核對期間發生變動" in reply


@pytest.mark.asyncio
async def test_apply_passes_verified_source_hash_and_requested_target(postwrite):
    backend, _ = postwrite
    event = await agent.apply_price(SimpleNamespace(state={}),
                                    {"quotation_number": ORIGINAL, "target_total": 200000})
    assert event.actions.route == "delegate"
    assert event.output["target_total"] == 200000
    assert event.output["original_source_sha256"] == agent.sha256_hex(agent.canonical_json(backend.quotations[ORIGINAL]))


@pytest.fixture
def converted(postwrite):
    backend, _ = postwrite
    source = backend.quotations[ORDER_SOURCE]
    existing = backend.orders.setdefault(str(source["customer_id"]), [])
    request = {"quotation_number": ORDER_SOURCE,
               "original_source_sha256": agent.sha256_hex(agent.canonical_json(source)),
               "original_order_ids": [row["id"] for row in existing]}
    order = {"id": 999, "order_number": ORDER, "quotation_id": source["id"],
             "customer_id": source["customer_id"], "status": "pending",
             "total_price": source["total_price"], "items": copy.deepcopy(source["items"])}
    existing.append(order)
    return backend, request, order


@pytest.mark.asyncio
async def test_convert_success_checks_full_order(converted):
    _, request, order = converted
    order["items"].reverse()
    reply = await agent._verify_after_write("convert_order", request, f"訂單編號: {ORDER}")
    assert f"後端查得到 {ORDER}，關聯 {ORDER_SOURCE}" in reply
    assert "新訂單客戶、產品、數量、單價與總價均符合" in reply


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["old_order", "wrong_customer", "wrong_quotation", "wrong_product",
                                   "wrong_quantity", "wrong_price", "wrong_subtotal", "wrong_total", "source_edited",
                                   "missing_items", "missing_before_ids"])
async def test_convert_false_success_is_rejected(converted, change):
    backend, request, order = converted
    if change == "old_order":
        request["original_order_ids"].append(order["id"])
    elif change == "wrong_customer":
        order["customer_id"] = 1000
    elif change == "wrong_quotation":
        order["quotation_id"] = 1000
    elif change == "wrong_product":
        order["items"][0]["product_id"] = 1000
    elif change == "wrong_quantity":
        order["items"][0]["quantity"] += 1
    elif change == "wrong_price":
        order["items"][0]["unit_price"] = "1"
    elif change == "wrong_subtotal":
        order["items"][0]["subtotal"] = "1"
    elif change == "wrong_total":
        order["total_price"] = "1"
    elif change == "source_edited":
        backend.quotations[ORDER_SOURCE]["notes"] += " edited"
    elif change == "missing_items":
        del order["items"]
    elif change == "missing_before_ids":
        del request["original_order_ids"]
    reply = await agent._verify_after_write("convert_order", request, f"訂單編號: {ORDER}")
    assert reply.startswith("改完後核對失敗：")
    assert "不能確認上方操作成功" in reply


@pytest.mark.asyncio
async def test_convert_rejects_inconsistent_historical_source(converted):
    backend, request, order = converted
    source = backend.quotations[ORDER_SOURCE]
    source["items"] = [{"product_id": 1, "quantity": 100, "unit_price": "1.23", "subtotal": "123.49"}]
    source["total_price"] = "123.49"
    request["original_source_sha256"] = agent.sha256_hex(agent.canonical_json(source))
    order["items"] = [{"product_id": 1, "quantity": 100, "unit_price": "1.23", "subtotal": "123.00"}]
    order["total_price"] = "123.00"
    reply = await agent._verify_after_write("convert_order", request, f"訂單編號: {ORDER}")
    assert "核對失敗" in reply


@pytest.mark.asyncio
async def test_order_delegate_carries_prewrite_snapshot(postwrite):
    backend, _ = postwrite
    source = backend.quotations[ORDER_SOURCE]
    event = await agent.order_check(SimpleNamespace(state={}),
                                    {"quotation_number": ORDER_SOURCE, "convert": True})
    assert event.actions.route == "delegate"
    assert event.output["original_source_sha256"] == agent.sha256_hex(agent.canonical_json(source))
    assert event.output["original_order_ids"] == [row["id"] for row in backend.orders.get(str(source["customer_id"]), [])]


@pytest.mark.asyncio
async def test_postwrite_backend_error_is_explicit_failure(postwrite, monkeypatch):
    backend, request = postwrite

    async def unavailable(number):
        raise BackendError("offline")

    monkeypatch.setattr(backend, "find_quotation", unavailable)
    reply = await agent._verify_after_write("apply_price", request, f"新報價單: {NEW}")
    assert reply.startswith("改完後核對失敗：")
    assert "不能確認上方操作成功" in reply
