from types import SimpleNamespace
import pytest
from pricing_advisor import agent
from pricing_advisor.write_intent import is_approval_query, is_polite_request, is_write_request

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
@pytest.mark.parametrize("label", ["off_topic", "provide_info", "apply_price", "quotation_request", "convert_order"])
def test_approval_question_wins_over_classifier_and_pending(text, label):
    assert is_approval_query(text)
    assert not is_write_request(text)
    assert not is_polite_request(text)
    ctx = SimpleNamespace(state={"last_user_text": text, "pending": {"intent": "apply_price", "target_total": 8000}, "last_check": {"quotation_number": "QT-20260330-001", "target_total": 8000}})
    event = agent.route(ctx, {"intent": label, "quotation_number": "QT-20260330-001"})
    expected = "policy_question" if any(word in text for word in ("複製", "訂單", "因子")) else "price_check"
    assert event.actions.route == expected
    if expected == "price_check":
        assert event.output == {"quotation_number": "QT-20260330-001", "target_total": 8000}
    assert event.actions.state_delta["pending"] is None
    assert event.actions.state_delta["last_check"] is None

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


@pytest.mark.parametrize("text", [
    "總價改成 8000 是否需要主管核准",
    "QT-20260330-001 改價是否需要主管核准",
    "QT-20260330-001 改成 8000 或 9000 是否需要主管核准",
    "QT-20260330-001 與 QT-20260325-001 改成 8000 是否需要主管核准",
    "QT-20260330-001x 改成 8000 是否需要主管核准",
])
def test_approval_question_does_not_fill_missing_or_ambiguous_values_from_history(text):
    state = {"last_user_text": text, "last_quotation": "QT-20260330-001",
             "pending": {"intent": "apply_price", "target_total": 12345},
             "last_check": {"quotation_number": "QT-20260330-001", "target_total": 12345}}
    event = agent.route(SimpleNamespace(state=state), {
        "intent": "apply_price", "quotation_number": "QT-20260330-001", "target_total": 12345})
    assert event.actions.route == "policy_question"
    assert event.actions.state_delta["pending"] is None
    assert event.actions.state_delta["last_check"] is None
