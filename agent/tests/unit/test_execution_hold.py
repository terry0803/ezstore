from types import SimpleNamespace
import pytest
from quotation_agent import agent
from quotation_agent.write_intent import has_execution_hold, is_write_request

@pytest.mark.parametrize('hold', ['先別執行','請別執行','別操作','别执行','請勿送出','不想執行','不需要提交','別真的寫入'])
@pytest.mark.parametrize('operation', ['複製報價單','把報價單轉成訂單'])
@pytest.mark.parametrize('label', ['off_topic','provide_info','duplicate_quotation','convert_to_order'])
def test_trailing_hold_blocks_whole_request_and_clears_pending(hold,operation,label):
    text=f'幫我{operation} QT-20260330-001；{hold}'
    assert has_execution_hold(text)
    assert not is_write_request(text)
    ctx=SimpleNamespace(state={'last_user_text':text,'pending_intent':{'intent':'duplicate_quotation'},'clarify_source_text':'請複製報價單'})
    e=agent.route(ctx, {'intent':label,'quotation_number':'QT-20260330-001'})
    assert e.actions.route=='off_topic'
    assert e.actions.state_delta['pending_intent'] is None
    assert e.actions.state_delta['clarify_source_text']==''

@pytest.mark.parametrize('text', ['請分別執行這兩項查詢','請特別執行檢查','能不能幫我複製報價單 QT-20260330-001'])
def test_non_negation_not_confused_with_hold(text):
    assert not has_execution_hold(text)
