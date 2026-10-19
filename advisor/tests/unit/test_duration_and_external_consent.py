from types import SimpleNamespace
import pytest
from pricing_advisor import agent
from pricing_advisor.write_intent import has_execution_hold, is_duration_query, is_write_request

Q = "QT-20260325-001"

@pytest.mark.parametrize("text", [
    f"請幫我確認複製報價單 {Q} 要多久？",
    f"幫我複製報價單 {Q} 要多久",
    f"請幫我把 {Q} 轉成訂單需要多少時間",
    f"把 {Q} 總價改成 300000 要幾分鐘",
    f"Please tell me how long it takes to copy quotation {Q}",
    f"等主管同意後，再把 {Q} 總價改成 300000",
    f"等待客戶確認，再複製報價單 {Q}",
    f"等王經理批准後，將 {Q} 轉成訂單",
    f"複製報價單 {Q}；待財務簽核後再執行",
    f"Wait for manager approval, then copy quotation {Q}",
    f"主管核准後才能把 {Q} 總價改成 300000",
])
@pytest.mark.parametrize("label", ["off_topic","provide_info","quotation_request","apply_price","convert_order"])
def test_inquiry_or_future_condition_never_writes_or_keeps_pending(text, label):
    assert is_duration_query(text) or has_execution_hold(text)
    assert not is_write_request(text)
    state = {"last_user_text":text,"pending":{"intent":"apply_price","target_total":300000},"last_check":{"quotation_number":Q,"target_total":300000}}
    event = agent.route(SimpleNamespace(state=state), {"intent": label, "quotation_number": Q})
    assert event.actions.route == "off_topic"
    assert event.actions.state_delta["pending"] is None
    assert event.actions.state_delta["last_check"] is None

@pytest.mark.parametrize("text", [
    f"請幫我複製報價單 {Q}",
    f"主管已同意，請把 {Q} 總價改成 300000",
    f"客戶等級已確認，請幫我複製報價單 {Q}",
])
def test_unconditional_requests_remain_supported(text):
    assert not has_execution_hold(text)
    assert not is_duration_query(text)
    assert is_write_request(text)
