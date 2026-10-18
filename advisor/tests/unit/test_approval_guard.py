import json
from types import SimpleNamespace
import pytest
from pricing_advisor import agent
from pricing_advisor.a2a_client import A2AResult

@pytest.mark.parametrize('prefix', ['不能', '不可以', '不可', '不准', '禁止', '不許', '不允許', '不得'])
@pytest.mark.parametrize('action', ['總價調到 200000', '因子設為 1.2', '複製', '轉成訂單'])
@pytest.mark.parametrize('label', ['off_topic', 'provide_info', 'apply_price', 'quotation_request'])
def test_prohibition_wins_over_classifier_and_pending(prefix, action, label):
    text=f'{prefix}把 QT-20260330-001 {action}'
    ctx=SimpleNamespace(state={'last_user_text':text,'pending':{'intent':'apply_price','quotation_number':'QT-20260330-001','target_total':200000},'last_check':{'target_total':200000}})
    e=agent.route(ctx,{'intent':label})
    assert e.actions.route == 'off_topic'
    assert e.actions.state_delta['pending'] is None
    assert e.actions.state_delta['last_check'] is None

@pytest.mark.asyncio
async def test_a2a_transports_exact_approval_and_explains_atomic_rejection(monkeypatch):
    approval={'source':{'id':1,'quotation_number':'QT-20260330-001'},'target_total':100,'factor':'1','total':'100','profit':'40'}
    calls=[]
    async def send(text):
        calls.append(text)
        return A2AResult(text='操作失敗：APPROVAL_CHANGED 核准版本已變更，沒有建立副本；請重新試算',task_id='12345678',context_id='ctx',state='completed',agent='quotation_agent')
    monkeypatch.setattr(agent,'quotation_agent',SimpleNamespace(send=send))
    result=await agent._send_a2a({'purpose':'apply_price','text':'請改價','quotation_number':'QT-20260330-001','target_total':100,'approval_snapshot':approval})
    marker, body=calls[0].split('\n',1)
    assert marker == 'EZSTORE_APPROVED_PRICE_V1'
    assert json.loads(body)['approval'] == approval
    assert '沒有建立副本' in result.output
    assert '改完後核對失敗' not in result.output

@pytest.mark.asyncio
async def test_missing_approval_cannot_use_unguarded_a2a(monkeypatch):
    async def forbidden(*a, **kw): pytest.fail('must not dispatch without approval')
    monkeypatch.setattr(agent,'quotation_agent',SimpleNamespace(send=forbidden))
    e=await agent._send_a2a({'purpose':'apply_price','text':'請改價'})
    assert '未送出操作' in e.output

@pytest.mark.asyncio
async def test_old_a2a_peer_is_rejected_before_send(monkeypatch):
    from pricing_advisor.a2a_client import QuotationAgentClient,A2AError
    client=QuotationAgentClient()
    async def card(_http): return SimpleNamespace(skills=[SimpleNamespace(id='adjust_total_price',tags=[])])
    def forbidden(*a): pytest.fail('old peer must not receive guarded request')
    monkeypatch.setattr(client,'fetch_card',card)
    monkeypatch.setattr(client,'_client',forbidden)
    with pytest.raises(A2AError) as error:
        await client.send('EZSTORE_APPROVED_PRICE_V1\n{}')
    assert error.value.may_have_written is False
