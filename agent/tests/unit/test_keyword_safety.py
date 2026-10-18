"""A rejected classification must not become an unrequested write."""

from types import SimpleNamespace

import pytest

from quotation_agent.agent import Intent, route


@pytest.mark.parametrize("text", [
    "不要複製報價單 QT-20260330-001",
    "先不要把報價單 QT-20260330-001 轉訂單",
    "教我如何複製報價單 QT-20260330-001",
    "如果複製報價單 QT-20260330-001，會發生什麼事？",
    "請說明把報價單 QT-20260330-001 總價改成 8000 的流程",
    "Do not show quotation QT-20260330-001",
])
def test_keyword_recovery_does_not_override_negation_or_explanation(text):
    ctx = SimpleNamespace(state={"last_user_text": text})
    event = route(ctx, Intent(intent="off_topic"))
    assert event.actions.route == "off_topic"
    assert event.actions.state_delta["pending_intent"] is None


@pytest.mark.parametrize("text,operation", [
    ("原單不要動，請複製報價單 QT-20260330-001", "duplicate_quotation"),
    ("請把報價單 QT-20260330-001 轉訂單", "convert_to_order"),
])
def test_keyword_recovery_retains_direct_requests(text, operation):
    ctx = SimpleNamespace(state={"last_user_text": text})
    event = route(ctx, Intent(intent="off_topic"))
    assert event.actions.route == operation


@pytest.mark.parametrize("text,operation", [
    ("不要複製報價單 QT-20260330-001", "duplicate_quotation"),
    ("先不要把報價單 QT-20260330-001 轉訂單", "convert_to_order"),
    ("請說明把報價單 QT-20260330-001 總價改成 8000 的流程", "adjust_total_price"),
])
def test_misclassified_negation_or_explanation_never_writes(text, operation):
    ctx = SimpleNamespace(state={
        "last_user_text": text,
        "pending_intent": {"intent": operation, "quotation_number": "QT-20260330-001"},
    })
    event = route(ctx, Intent(intent=operation))
    assert event.actions.route == "off_topic"
    assert event.actions.state_delta["pending_intent"] is None


@pytest.mark.parametrize("classification", ["off_topic", "duplicate_quotation"])
@pytest.mark.parametrize("text", [
    "不要修改原單，請複製報價單 QT-20260330-001",
    "請複製報價單 QT-20260330-001，不要修改原單",
    "不要動原單，請複製報價單 QT-20260330-001",
    "原單不要修改，請複製報價單 QT-20260330-001",
    "請勿變更原始報價單內容；請複製報價單 QT-20260330-001",
    "如果可以，請複製報價單 QT-20260330-001",
])
def test_preserving_original_and_polite_copy_are_direct_requests(text, classification):
    event = route(SimpleNamespace(state={"last_user_text": text}), Intent(intent=classification))
    assert event.actions.route == "duplicate_quotation"
    assert event.output == {"quotation_number": "QT-20260330-001"}


@pytest.mark.parametrize("classification", ["off_topic", "duplicate_quotation"])
@pytest.mark.parametrize("text", [
    "不要修改原單，也不要複製報價單 QT-20260330-001",
    "不要複製報價單 QT-20260330-001，不要修改原單",
    "不要修改原單，請說明如何複製報價單 QT-20260330-001",
    "不要修改原單，假設複製報價單 QT-20260330-001會怎樣？",
    "如果可以，請說明複製報價單 QT-20260330-001的流程",
    "如果可以，請複製報價單 QT-20260330-001的流程說明給我",
])
def test_preservation_and_politeness_do_not_override_real_refusals(text, classification):
    event = route(SimpleNamespace(state={"last_user_text": text}), Intent(intent=classification))
    assert event.actions.route == "off_topic"
    assert event.actions.state_delta["pending_intent"] is None


@pytest.mark.parametrize("text", ["不要修改原單", "不要動原單", "原單不要動", "請勿變更原始報價單內容"])
def test_preservation_only_does_not_confirm_pending_copy(text):
    event = route(SimpleNamespace(state={
        "last_user_text": text,
        "pending_intent": {"intent": "duplicate_quotation", "quotation_number": "QT-20260330-001"},
    }), Intent(intent="provide_info"))
    assert event.actions.route == "off_topic"
    assert event.actions.state_delta["pending_intent"] is None


@pytest.mark.parametrize("text,operation", [
    ("請不要用 Markdown 格式顯示報價單 QT-20260330-001 的內容", "get_quotation"),
    ("請分別查詢報價單 QT-20260330-001", "get_quotation"),
    ("特別麻煩你把 QT-20260330-001 總價改為 8000", "adjust_total_price"),
    ("如果可以，請把 QT-20260330-001 轉訂單", "convert_to_order"),
    ("如果方便的話，幫我將報價單 QT-20260330-001 轉訂單", "convert_to_order"),
    ("如果可以的話請幫我把 QT-20260330-001 報價因子改為 1.2", "update_pricing_factor"),
])
def test_ordinary_wording_is_not_mistaken_for_negation_or_hypothesis(text, operation):
    """「分別」「特別」不是否定；「不要用 Markdown」否定的是格式；「如果可以，請…」是禮貌請求。"""
    event = route(SimpleNamespace(state={"last_user_text": text}), Intent(intent=operation))
    assert event.actions.route == operation


@pytest.mark.parametrize("text", [
    "如果把 QT-20260330-001 轉訂單，會怎樣？",
    "如果可以，請把 QT-20260330-001 轉訂單嗎？",
    "別把 QT-20260330-001 轉訂單",
])
def test_real_hypotheses_and_negations_still_refused(text):
    event = route(SimpleNamespace(state={"last_user_text": text}), Intent(intent="convert_to_order"))
    assert event.actions.route == "off_topic"
