from types import SimpleNamespace
import pytest
from quotation_agent import agent
from quotation_agent.write_intent import is_approval_query, is_polite_request, is_write_request

QUESTIONS = [
    "幫我確認 QT-20260330-001 總價改成 8000 是否需要主管核准",
    "幫我把 QT-20260330-001 總價改成 8000，需要誰核准",
    "幫我把 QT-20260330-001 總價改成 8000，誰來核准",
    "幫我複製報價單 QT-20260330-001 需不需要主管核准",
    "幫我把 QT-20260330-001 轉成訂單，要不要簽核",
    "幫我把 QT-20260330-001 報價因子改成 1.2，是否須經主管批准",
    "哪位主管核准才能把 QT-20260330-001 總價改成 8000",
    "幫我把 QT-20260330-001 總價改成 8000 的核准門檻是什麼",
    "帮我把 QT-20260330-001 总价改成 8000，是否需要主管审批",
    "幫我把 QT-20260330-001 總價改成 8000 需要主管核准嗎",
    "Please change QT-20260330-001 total to 8000; whose approval is required",
]

@pytest.mark.parametrize("text", QUESTIONS)
@pytest.mark.parametrize("label", ["off_topic", "provide_info", "adjust_total_price", "duplicate_quotation", "convert_to_order"])
def test_approval_question_wins_over_classifier_and_pending(text, label):
    assert is_approval_query(text)
    assert not is_write_request(text)
    assert not is_polite_request(text)
    ctx = SimpleNamespace(state={"last_user_text": text, "pending_intent": {"intent": "adjust_total_price", "target_total_price": 8000}, "clarify_source_text": "請幫我改總價"})
    event = agent.route(ctx, {"intent": label, "quotation_number": "QT-20260330-001"})
    assert event.actions.route == "off_topic"
    assert event.actions.state_delta["pending_intent"] is None
    assert event.actions.state_delta["clarify_source_text"] == ""
    assert agent._keyword_operation(text) is None

@pytest.mark.parametrize("text", [
    "請把 QT-20260330-001 總價改成 8000",
    "主管已核准，請把 QT-20260330-001 總價改成 8000",
    "請複製報價單 QT-20260330-001",
    "能不能幫我把 QT-20260330-001 轉成訂單",
    "Please change QT-20260330-001 total to 8000",
])
def test_explicit_requests_are_not_approval_questions(text):
    assert not is_approval_query(text)
    assert is_write_request(text)
