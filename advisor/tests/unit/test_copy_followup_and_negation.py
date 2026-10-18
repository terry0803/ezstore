from types import SimpleNamespace
import pytest
from pricing_advisor import agent
from pricing_advisor.write_intent import is_write_request

def route(text, label='quotation_request', state=None):
    return agent.route(SimpleNamespace(state={'last_user_text':text, **(state or {})}), {'intent':label})

@pytest.mark.parametrize('action',['調到','設為','設定成','變更為','變成','改成','壓到','降到','轉成訂單','複製'])
@pytest.mark.parametrize('label',['quotation_request','apply_price','provide_info','off_topic'])
def test_negated_verbs_never_use_old_pending_or_price(action,label):
    text=f'不要把 QT-20260330-001 的總價{action} 200000'
    assert not is_write_request(text)
    e=route(text,label,{'pending':{'intent':'apply_price','quotation_number':'QT-20260330-001','target_total':200000},'last_check':{'target_total':200000}})
    assert e.actions.route=='off_topic'
    assert e.actions.state_delta['pending'] is None
    assert e.actions.state_delta['last_check'] is None

def start_copy():
    e=route('幫我複製報價單',state={'last_quotation':'QT-20260325-001'})
    assert e.actions.route=='clarify'
    assert '尚未送出' in agent.clarify(e.output)
    return e.actions.state_delta

@pytest.mark.parametrize('label',['provide_info','quotation_request','off_topic','apply_price'])
@pytest.mark.parametrize('text',['QT-20260330-001','qt-20260330-001','編號是 QT-20260330-001','報價單編號：QT-20260330-001'])
def test_copy_collects_number_locally_and_delegates_once(text,label):
    e=route(text,label,start_copy())
    assert e.actions.route=='delegate'
    assert e.output['writes'] is True
    assert e.output['text']=='我要複製報價單，報價單編號：QT-20260330-001'
    assert e.actions.state_delta['pending'] is None
    after=route('QT-20260330-001','provide_info',e.actions.state_delta)
    assert after.output['writes'] is False

@pytest.mark.parametrize('text,label',[
    ('取消','provide_info'),('不要複製','quotation_request'),
    ('請確認是否已複製報價單 QT-20260330-001','quotation_request'),
    ('天氣如何','off_topic'),('請查詢 QT-20260330-001','quotation_request'),
    ('QT-20260330-001 和 QT-20260325-001','provide_info'),
    ('QT-20260330-001ABC','provide_info'),
])
def test_cancel_status_lookup_or_ambiguity_does_not_inherit_copy(text,label):
    e=route(text,label,start_copy())
    assert e.actions.route!='delegate' or e.output['writes'] is False
    assert e.actions.state_delta['pending'] is None
    next_event=route('QT-20260330-001','provide_info',e.actions.state_delta)
    assert next_event.output['writes'] is False
