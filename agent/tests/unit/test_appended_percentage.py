from types import SimpleNamespace
import pytest
from quotation_agent import agent

@pytest.mark.parametrize("delta", ["再加 10%", "再減 10%", "再調高 １０％", "再降低 10 %", "再加 5000"])
@pytest.mark.parametrize("pending", [False, True])
def test_appended_adjustment_requires_final_target(delta, pending):
    text = "請把報價單 QT-20260330-001 總價改成 20 萬" + delta
    state = {"last_user_text": text, "clarify_source_text": "總價改成 200000",
             "pending_intent": {"intent":"adjust_total_price", "target_total_price":200000} if pending else None}
    event = agent.route(SimpleNamespace(state=state), {
        "intent": "provide_info" if pending else "adjust_total_price", "target_total_price": 200000})
    assert event.actions.route == "clarify"
    assert event.output["fields"]["target_total_price"] is None
    assert event.actions.state_delta["pending_intent"]["target_total_price"] is None

@pytest.mark.parametrize("tail", ["", "，毛利率為 10%", "，數量 10 件"])
def test_unrelated_percent_and_quantity_do_not_remove_explicit_total(tail):
    event = agent.route(SimpleNamespace(state={"last_user_text":"請把報價單 QT-20260330-001 總價改成 20 萬" + tail}),
                        {"intent":"adjust_total_price", "target_total_price":200000})
    assert event.actions.route == "adjust_total_price"
    assert event.output["target_total_price"] == 200000
