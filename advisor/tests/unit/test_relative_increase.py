from types import SimpleNamespace
import pytest
from pricing_advisor import agent

Q = "QT-20260325-001"

@pytest.mark.parametrize("change", ["調高 300000", "調高三十萬", "提高 300000", "增加 300000", "調低 300000", "降 300000", "改成 300000 再調高 1000"])
@pytest.mark.parametrize("label", ["apply_price", "price_check", "quotation_request"])
def test_relative_amount_requires_absolute_target_even_with_history(change, label):
    state = {"last_user_text": f"幫我把 {Q} 總價{change}",
             "pending": {"intent": "apply_price", "target_total": 300000},
             "last_check": {"quotation_number": Q, "target_total": 300000}}
    event = agent.route(SimpleNamespace(state=state), {"intent": label, "target_total": 300000})
    assert event.actions.route == "clarify"
    assert event.output["fields"]["target_total"] is None
    assert event.output["hint"] == "relative"
    assert event.actions.state_delta["last_check"] is None

@pytest.mark.parametrize("change", ["調高到 300000", "降到 300000", "調到 300000", "改成 300000"])
def test_absolute_target_remains_executable(change):
    event = agent.route(SimpleNamespace(state={"last_user_text": f"幫我把 {Q} 總價{change}"}), {"intent": "apply_price"})
    assert event.actions.route == "apply_price"
    assert event.output["target_total"] == 300000

def test_relative_approval_question_cannot_report_incorrect_price_check():
    text = f"幫我確認 {Q} 總價調高 300000 是否需要主管核准"
    event = agent.route(SimpleNamespace(state={"last_user_text": text}), {"intent": "apply_price"})
    assert event.actions.route == "policy_question"
