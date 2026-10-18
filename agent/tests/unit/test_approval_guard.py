import json
from types import SimpleNamespace
import pytest
from quotation_agent import agent
from quotation_agent.write_intent import is_write_request

@pytest.mark.parametrize('prefix', ['不能', '不可以', '不可', '不准', '禁止', '不許', '不允許', '不得'])
@pytest.mark.parametrize('action', ['總價調到 200000', '因子設為 1.2', '複製', '轉成訂單'])
@pytest.mark.parametrize('label', ['off_topic', 'provide_info', 'adjust_total_price', 'convert_to_order'])
def test_prohibition_wins_over_classifier_and_pending(prefix, action, label):
    text = f'{prefix}把 QT-20260330-001 {action}'
    assert not is_write_request(text)
    ctx = SimpleNamespace(state={'last_user_text':text, 'pending_intent':{'intent':'adjust_total_price','quotation_number':'QT-20260330-001'}, 'clarify_source_text':'請改價'})
    event = agent.route(ctx, {'intent':label,'target_total_price':200000})
    assert event.actions.route == 'off_topic'
    assert event.actions.state_delta['pending_intent'] is None

def payload():
    return {'quotation_number':'QT-20260330-001', 'target_total_price':100,
            'approval':{'source':{'id':1,'quotation_number':'QT-20260330-001'}, 'target_total':100,'factor':'1','total':'100','profit':'40'}}

@pytest.mark.asyncio
async def test_machine_approval_passes_unchanged_without_model_or_new_preflight(monkeypatch):
    args = payload()
    event = agent.load_context(SimpleNamespace(state={}), 'EZSTORE_APPROVED_PRICE_V1\n'+json.dumps(args))
    assert event.actions.route == 'approved_price'
    calls=[]
    async def call(_ctx, name, forwarded):
        calls.append((name,forwarded)); return 'ok'
    async def forbidden(*a, **kw):
        pytest.fail('guarded operation must not replace the approved snapshot')
    monkeypatch.setattr(agent,'_call_mcp_tool',call)
    monkeypatch.setattr(agent,'validate_change',forbidden)
    assert await agent.adjust_total_price(None, event.output) == 'ok'
    assert calls == [('adjust_total_price',args)]

@pytest.mark.parametrize('body', ['{}','null','[]','bad json', '{"quotation_number":"QT-20260330-001"}'])
def test_malformed_guard_never_falls_back_to_classifier(body):
    e=agent.load_context(SimpleNamespace(state={}), 'EZSTORE_APPROVED_PRICE_V1\n'+body)
    assert e.actions.route == 'no_credentials'
    assert '未送出操作' in e.output

def test_mismatched_guard_is_rejected():
    args=payload(); args['target_total_price']=200
    e=agent.load_context(SimpleNamespace(state={}), 'EZSTORE_APPROVED_PRICE_V1\n'+json.dumps(args))
    assert e.actions.route == 'no_credentials'

def test_polite_can_you_is_still_authorized():
    assert is_write_request('能不能把 QT-20260330-001 總價改成 200000？')
    assert is_write_request('可不可以把 QT-20260330-001 總價改成 200000？')

@pytest.mark.parametrize('text', ['不能', '不准', '禁止', '不可以執行，總價 200000'])
def test_prohibition_alone_cancels_pending(text):
    ctx=SimpleNamespace(state={'last_user_text':text,'pending_intent':{'intent':'adjust_total_price','quotation_number':'QT-20260330-001'},'clarify_source_text':'請改價'})
    e=agent.route(ctx, {'intent':'provide_info','target_total_price':200000})
    assert e.actions.route=='off_topic'
    assert e.actions.state_delta['pending_intent'] is None

@pytest.mark.asyncio
async def test_old_mcp_cannot_drop_approval(monkeypatch):
    async def forbidden(**kw): pytest.fail('old MCP must never receive guarded writes')
    async def get_tools(): return [SimpleNamespace(name='adjust_total_price',run_async=forbidden)]
    monkeypatch.setattr(agent,'mcp_toolset',SimpleNamespace(get_tools=get_tools))
    reply=await agent._call_mcp_tool(None,'adjust_total_price',payload())
    assert '未送出操作' in reply

@pytest.mark.asyncio
@pytest.mark.parametrize('schema_name', ['input_schema','inputSchema'])
async def test_atomic_conflict_does_not_claim_possible_draft(monkeypatch, schema_name):
    async def run_async(**kw):
        return {'isError':True,'content':[{'type':'text','text':'後端回應 409：APPROVAL_CHANGED 沒有建立副本'}]}
    async def get_tools():
        return [SimpleNamespace(name='adjust_total_price',run_async=run_async,
                raw_mcp_tool=SimpleNamespace(**{schema_name:{'properties':{'approval':{}}}}))]
    monkeypatch.setattr(agent,'mcp_toolset',SimpleNamespace(get_tools=get_tools))
    reply=await agent._call_mcp_tool(None,'adjust_total_price',payload())
    assert '沒有建立副本' in reply
    assert '可能已經建立' not in reply
