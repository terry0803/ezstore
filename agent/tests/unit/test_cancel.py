"""使用者說不要做了，就清掉待補的操作，不能拿上一輪記住的值去改資料。"""

from types import SimpleNamespace

import pytest

from quotation_agent.agent import CANCEL_TEXT, EXPLAIN_TEXT, Intent, route

Q = "QT-20260330-001"
PENDING = {"intent": "adjust_total_price", "quotation_number": None, "target_total_price": 8000.0}


@pytest.mark.parametrize("text", [
    f"先不要改了，{Q}",
    f"不要改了 {Q}",
    f"不要改 {Q}",
    f"算了不改了，{Q}",
    f"取消，{Q}",
    "算了",
    "不用了",
    f"先不用轉了，{Q}",
    f"取消剛剛的修改，{Q}",
])
@pytest.mark.parametrize("classified", ["provide_info", "adjust_total_price", "off_topic"])
def test_cancel_after_clarify_never_writes(text, classified):
    """報告重現的情境：先說「請將總價改成 8000」，再說「先不要改了，QT-…」。"""
    event = route(SimpleNamespace(state={"last_user_text": text, "pending_intent": PENDING}),
                  Intent(intent=classified, quotation_number=Q if Q in text else None))
    assert event.actions.route == "off_topic"
    assert event.output == CANCEL_TEXT
    assert event.actions.state_delta["pending_intent"] is None


@pytest.mark.parametrize("text,operation", [
    (f"不要改原單，請複製報價單 {Q}", "duplicate_quotation"),
    (f"我要修改報價單總價，報價單編號：{Q}，總價改為 8000", "adjust_total_price"),
    (f"請不要用 Markdown 格式顯示報價單 {Q} 的內容", "get_quotation"),
])
def test_ordinary_requests_are_not_cancellations(text, operation):
    intent = Intent(intent=operation, quotation_number=Q, target_total_price=8000 if "8000" in text else None)
    event = route(SimpleNamespace(state={"last_user_text": text, "pending_intent": None}), intent)
    assert event.actions.route == operation


def test_explanation_question_gets_an_explanation_not_a_refusal():
    event = route(SimpleNamespace(state={"last_user_text": f"教我如何複製報價單 {Q}"}),
                  Intent(intent="duplicate_quotation", quotation_number=Q))
    assert event.actions.route == "off_topic"
    assert event.output == EXPLAIN_TEXT
