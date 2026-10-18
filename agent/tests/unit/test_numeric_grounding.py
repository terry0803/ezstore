"""Raw target parsing must not trust an unrelated/partial model number."""
from types import SimpleNamespace

import pytest

from quotation_agent.agent import Intent, route

QUOTE = "QT-20260325-001"


def result(text, value, *, factor=False, pending=None, source=""):
    field = "new_pricing_factor" if factor else "target_total_price"
    operation = "update_pricing_factor" if factor else "adjust_total_price"
    intent = Intent(intent="provide_info" if pending else operation, **{field: value})
    event = route(SimpleNamespace(state={"last_user_text": text, "pending_intent": pending,
                                        "clarify_source_text": source}), intent)
    return event, field, operation


@pytest.mark.parametrize(("text", "value", "factor", "expected"), [
    (f"把 {QUOTE} 總價改成18萬", 18, False, 180000),
    (f"把 {QUOTE} 總價改成一點五萬", 1.5, False, 15000),
    (f"把 {QUOTE} 報價因子從0.85改成0.9", 0.85, True, 0.9),
])
def test_review_counterexamples_use_unambiguous_raw_target(text, value, factor, expected):
    event, field, _ = result(text, value, factor=factor)
    assert event.actions.route in {"adjust_total_price", "update_pricing_factor"}
    assert event.output[field] == expected


def test_review_counterexample_never_drops_unicode_negative_sign():
    event, field, _ = result(f"把 {QUOTE} 報價因子改成−1", 1, factor=True)
    assert event.actions.route == "clarify"
    assert field in event.output["missing"] + event.output["invalid"]


@pytest.mark.parametrize(("text", "value"), [
    ("18萬", 180000), ("18 萬", 180000), ("一點五萬", 15000),
    ("一點五 萬", 15000), ("1.5萬", 15000),
    ("十萬", 100000), ("十八萬五千", 185000), ("18萬5千", 185000),
    ("八千", 8000), ("8千", 8000), ("0.5萬", 5000), ("兩千三百四十五", 2345),
    ("一億二千萬", 120000000), ("二百零五", 205), ("一萬零二", 10002),
])
def test_complete_unit_expressions_are_grounded_as_one_amount(text, value):
    event, field, operation = result(f"{QUOTE} 總價改為{text}", value)
    assert event.actions.route == operation
    assert event.output[field] == value


@pytest.mark.parametrize(("text", "value", "factor"), [
    (f"{QUOTE} 因子從0.85改成0.9", 0.9, True),
    (f"{QUOTE} 因子由一點五變成一點二", 1.2, True),
    (f"{QUOTE} factor from 0.85 to 0.9", 0.9, True),
    (f"{QUOTE} 總價從20萬壓到18萬", 180000, False),
    (f"{QUOTE} 總價200000改成180000", 180000, False),
    (f"{QUOTE} 總價原本20萬，改成18萬", 180000, False),
    (f"{QUOTE} 總價改成18萬，數量10件", 180000, False),
    (f"{QUOTE} 總價改成18萬，因子0.9", 180000, False),
    (f"{QUOTE} 因子改成0.9，總價18萬", 0.9, True),
])
def test_only_the_correct_field_and_target_role_is_used(text, value, factor):
    event, field, operation = result(text, value, factor=factor)
    assert event.actions.route == operation
    assert event.output[field] == value


@pytest.mark.parametrize(("text", "value", "factor"), [
    (f"{QUOTE} 總價改成8000或9000", 8000, False),
    (f"{QUOTE} 總價改成8000，9000", 8000, False),
    (f"{QUOTE} 總價改成8000再改成9000", 9000, False),
    (f"{QUOTE} 因子從0.85", 0.85, True),
    (f"{QUOTE} 總價減少8000", 8000, False),
    (f"{QUOTE} 總價原本20000，減少8000", 20000, False),
    (f"{QUOTE} 因子增加0.1", 0.1, True),
    (f"{QUOTE} 總價最多8000", 8000, False),
    (f"{QUOTE} 總價改為8000件", 8000, False),
    (f"{QUOTE} 總價改為2026/10/17", 2026, False),
    (f"{QUOTE} 因子改為20%", 20, True),
    (f"{QUOTE} 因子改為1.5元", 1.5, True),
    (f"{QUOTE} 總價改成18萬5", 180005, False),
    (f"{QUOTE} 總價改成一萬二", 10002, False),
    (f"{QUOTE} 總價改成二百五", 205, False),
    (f"{QUOTE} 總價18萬，因子0.9", 0.9, False),
    (f"{QUOTE} 因子0.9，總價18萬", 180000, True),
])
def test_ambiguous_relative_quantity_date_or_other_field_is_not_a_target(text, value, factor):
    event, _, _ = result(text, value, factor=factor)
    assert event.actions.route == "clarify"


@pytest.mark.parametrize("minus", ["-", "−", "－", "﹣", "負", "负", "- "])
@pytest.mark.parametrize("model_value", [-1, 1])
def test_negative_sign_is_never_dropped(minus, model_value):
    event, _, _ = result(f"{QUOTE} 因子改成{minus}1", model_value, factor=True)
    assert event.actions.route == "clarify"


def test_missing_model_number_can_use_an_unambiguous_raw_target():
    event, field, operation = result(f"{QUOTE} 總價改成18萬", None)
    assert event.actions.route == operation
    assert event.output[field] == 180000


@pytest.mark.parametrize(("answer", "value"), [("0.9", 0.9), ("一點五", 1.5)])
def test_bare_answer_is_allowed_only_for_the_pending_field(answer, value):
    pending = {"intent": "update_pricing_factor", "quotation_number": QUOTE, "new_pricing_factor": None}
    event, field, operation = result(answer, value, factor=True, pending=pending)
    assert event.actions.route == operation
    assert event.output[field] == value


def test_quantity_answer_cannot_replace_or_resurrect_pending_price():
    pending = {"intent": "adjust_total_price", "quotation_number": QUOTE, "target_total_price": 8000}
    event, _, _ = result("20件", 8000, pending=pending)
    assert event.actions.route == "clarify"


def test_current_invalid_value_never_falls_back_to_history():
    event, _, _ = result(f"{QUOTE} 因子改成−1", 1.5, factor=True, source="因子改成1.5")
    assert event.actions.route == "clarify"


def test_history_target_survives_quote_only_answer():
    event, field, operation = result(QUOTE, 15000, source="請改總價為一點五萬")
    assert event.actions.route == operation
    assert event.output[field] == 15000
