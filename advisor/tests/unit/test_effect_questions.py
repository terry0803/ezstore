from types import SimpleNamespace
import pytest
from pricing_advisor import agent
from pricing_advisor.write_intent import is_write_request, is_polite_request

Q = "QT-20260330-001"

@pytest.mark.parametrize("text", [
    f"可以幫我確認複製報價單 {Q} 會不會覆蓋原單？",
    f"幫我複製報價單 {Q} 是否會覆蓋原單",
    f"複製報價單 {Q} 會否影響原單",
    f"請確認把 {Q} 轉成訂單會不會刪掉報價單",
    f"幫我確認 {Q} 改成 8000 有何影響",
    f"Can you confirm whether copying {Q} will overwrite the original?",
])
@pytest.mark.parametrize("label", ["off_topic","provide_info","quotation_request","apply_price","convert_order"])
def test_effect_question_cannot_authorize_or_resume_write(text, label):
    assert not is_write_request(text)
    assert not is_polite_request(text)
    state = {"last_user_text":text,"pending":{"intent":"quotation_request","operation":"duplicate_quotation"},"last_check":{"quotation_number":Q,"target_total":8000}}
    event = agent.route(SimpleNamespace(state=state), {"intent":label, "quotation_number":Q})
    assert event.actions.route == "off_topic"
    assert event.actions.state_delta["pending"] is None
    assert event.actions.state_delta["last_check"] is None

@pytest.mark.parametrize("text", [
    f"請幫我複製報價單 {Q}",
    f"我知道複製不會覆蓋原單，請複製報價單 {Q}",
])
def test_explicit_copy_request_still_authorized(text):
    assert is_write_request(text)
