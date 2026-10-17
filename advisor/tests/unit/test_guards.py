"""否定、取消、問做法、金額有歧義：這些句子都不能變成寫入（外部審查回報的情境）。"""

from types import SimpleNamespace

import pytest

import pricing_advisor.agent as advisor
from pricing_advisor.agent import CANCEL_TEXT, EXPLAIN_TEXT, AdvisorIntent

Q = "QT-20260325-001"
COPY = "QT-20260330-001"


def run(text, intent, state=None):
    number = Q if Q in text else (COPY if COPY in text else None)
    ctx = SimpleNamespace(state={"last_user_text": text, **(state or {})})
    return advisor.route(ctx, AdvisorIntent(intent=intent, quotation_number=number))


@pytest.mark.parametrize("text,expected", [
    (f"教我如何複製報價單 {COPY}", EXPLAIN_TEXT),
    (f"不要複製報價單 {COPY}", CANCEL_TEXT),
])
def test_explanation_or_negated_copy_is_not_sent(text, expected):
    event = run(text, "quotation_request")
    assert event.actions.route == "off_topic"
    assert event.output == expected


@pytest.mark.parametrize("text,verb", [
    (f"不要修改原單，請複製報價單 {COPY}", "複製"),
    (f"Copy quotation {COPY}", "複製"),
    (f"Please duplicate {COPY}", "複製"),
    (f"幫我查報價單 {COPY}", "查詢"),
])
def test_copy_and_query_requests_are_sent_correctly(text, verb):
    event = run(text, "quotation_request")
    assert event.actions.route == "delegate"
    assert event.output["text"] == f"我要{verb}報價單，報價單編號：{COPY}"


@pytest.mark.parametrize("amount", ["200000 或 210000", "200000 還是 210000", "200000 到 210000", "18萬5", "一萬二", "二百五"])
def test_ambiguous_amount_asks_instead_of_choosing(amount):
    event = run(f"幫我把 {Q} 總價改成 {amount}", "apply_price")
    assert event.actions.route == "clarify"
    assert event.output["hint"] == "amount"


def test_ambiguous_amount_does_not_fall_back_to_the_last_check():
    last = {"quotation_number": Q, "target_total": 200000.0, "approval": "none"}
    event = run(f"那就幫我把 {Q} 改成 200000 或 210000", "apply_price", {"last_check": last, "last_quotation": Q})
    assert event.actions.route == "clarify"


@pytest.mark.parametrize("text,value", [
    (f"幫我把 {Q} 壓到 20 萬", 200000.0),
    (f"幫我把 {Q} 壓到十八萬五千", 185000.0),
    (f"幫我把 {Q} 從 211560 壓到 200000", 200000.0),
    (f"2026/10/17 客戶說 {Q} 想壓到 190000", 190000.0),
])
def test_clear_amounts_still_parse(text, value):
    event = run(text, "apply_price")
    assert event.actions.route == "apply_price"
    assert event.output["target_total"] == value


@pytest.mark.parametrize("text,intent", [
    (f"先不要改了，{Q}", "apply_price"),
    (f"不要把 {Q} 改成 200000", "apply_price"),
    (f"不要把 {COPY} 轉成訂單", "convert_order"),
    ("算了", "provide_info"),
])
def test_cancellation_clears_state_and_never_writes(text, intent):
    event = run(text, intent, {"pending": {"intent": "apply_price", "quotation_number": Q, "target_total": None}})
    assert event.actions.route == "off_topic"
    assert event.output == CANCEL_TEXT
    assert event.actions.state_delta["pending"] is None and event.actions.state_delta["last_check"] is None


def test_explanation_about_conversion_only_checks():
    event = run(f"教我怎麼把 {COPY} 轉成訂單", "convert_order")
    assert event.actions.route == "order_check"
    assert event.output["convert"] is False


def test_policy_question_with_negation_is_still_answered():
    event = run("業務可不可以不用主管核准就改價？", "policy_question")
    assert event.actions.route == "policy_question"
