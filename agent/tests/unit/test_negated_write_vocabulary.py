from types import SimpleNamespace
import pytest
from quotation_agent import agent
from quotation_agent.write_intent import has_negated_write, is_write_request

@pytest.mark.parametrize('action', ['調到','調整為','設為','設定成','設成','變更為','變成','改成','壓到','降到','轉成訂單','複製','set','adjust','copy','convert'])
@pytest.mark.parametrize('label', ['off_topic','provide_info','adjust_total_price'])
def test_every_write_verb_is_blocked_before_recovery(action,label):
    text=f'不要把 QT-20260330-001 的總價{action} 200000'
    assert has_negated_write(text)
    assert not is_write_request(text)
    assert agent._keyword_operation(text) is None
    event=agent.route(SimpleNamespace(state={'last_user_text':text,'pending_intent':{'intent':'adjust_total_price','quotation_number':'QT-20260330-001'},'clarify_source_text':'請修改總價'}), {'intent':label,'target_total_price':200000})
    assert event.actions.route=='off_topic'
    assert event.actions.state_delta['pending_intent'] is None
    assert event.actions.state_delta['clarify_source_text']==''

@pytest.mark.parametrize('prefix',['請勿','別','不必','不用','不想','先不','暫時不'])
def test_negation_does_not_expire_after_sixty_characters(prefix):
    text=prefix+'把客戶'+('甲'*80)+'的報價單 QT-20260330-001 總價調到 200000'
    assert has_negated_write(text)
    assert not is_write_request(text)

@pytest.mark.parametrize('text', [
    '不要用 1.2 作為 QT-20260330-001 的因子設定值',
    '不要以 200000 為目標把 QT-20260330-001 的總價調到該值',
])
def test_negated_method_does_not_authorize_write(text):
    assert has_negated_write(text)
    assert not is_write_request(text)
