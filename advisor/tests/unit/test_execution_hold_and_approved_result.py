import copy
from decimal import Decimal, ROUND_HALF_UP
from types import SimpleNamespace
import pytest
from pricing_advisor import agent
from pricing_advisor.okf import Bundle
from pricing_advisor.write_intent import has_execution_hold,is_write_request

@pytest.mark.parametrize('hold', ['先別執行','請別執行','別操作','别执行','請勿送出','不想執行','不需要提交','別真的寫入'])
@pytest.mark.parametrize('operation', ['複製報價單','把報價單轉成訂單'])
@pytest.mark.parametrize('label', ['off_topic','provide_info','quotation_request','convert_order'])
def test_trailing_hold_blocks_whole_request_and_clears_pending(hold,operation,label):
    text=f'幫我{operation} QT-20260330-001；{hold}'
    assert has_execution_hold(text)
    assert not is_write_request(text)
    ctx=SimpleNamespace(state={'last_user_text':text,'pending':{'intent':'quotation_request','operation':'duplicate_quotation'},'last_check':{'quotation_number':'QT-20260330-001','target_total':200000}})
    e=agent.route(ctx, {'intent':label,'quotation_number':'QT-20260330-001'})
    assert e.actions.route=='off_topic'
    assert e.actions.state_delta['pending'] is None
    assert e.actions.state_delta['last_check'] is None

async def approved_fixture(fake_backend,bundle_path,monkeypatch,target=320):
    q=copy.deepcopy(await fake_backend.find_quotation('QT-20260330-001'))
    q.update(customer_level='vip',pricing_factor='1',total_price='400',profit_amount='300',profit_rate='0.75',status='draft')
    q['customer']['level']='vip'
    i=copy.deepcopy(q['items'][0])
    i.update(list_price='0.04',product_cost='0.01',quantity=10000,unit_price='0.04',subtotal='400')
    q['items']=[i]
    fake_backend.quotations={q['quotation_number']:q}
    fake_backend.products={i['product_id']:{'list_price':'0.04','cost':'0.01'}}
    monkeypatch.setattr(agent,'backend',fake_backend)
    monkeypatch.setattr(agent,'_bundle',lambda:Bundle(bundle_path))
    event=await agent.apply_price(SimpleNamespace(state={}),{'quotation_number':q['quotation_number'],'target_total':target})
    assert event.actions.route=='delegate'
    approved=event.output['approval_snapshot']
    new=copy.deepcopy(q)
    new.update(id=q['id']+1000,quotation_number='QT-20261018-999',pricing_factor=approved['factor'],total_price=approved['total'],profit_amount=approved['profit'])
    unit=(Decimal('0.04')*Decimal(approved['factor'])).quantize(Decimal('.01'),rounding=ROUND_HALF_UP)
    new['items'][0].update(unit_price=str(unit),subtotal=str(unit*10000))
    new['profit_rate']=str((Decimal(approved['profit'])/Decimal(approved['total'])).quantize(Decimal('.0001'),rounding=ROUND_HALF_UP))
    fake_backend.quotations[new['quotation_number']]=new
    return event.output,new

@pytest.mark.asyncio
@pytest.mark.parametrize('target,direction,gap', [(320,'高於','80'),(910,'低於','10'),(400,None,None)])
async def test_approved_plateau_is_success_with_honest_target_gap(fake_backend,bundle_path,monkeypatch,target,direction,gap):
    request,new=await approved_fixture(fake_backend,bundle_path,monkeypatch,target)
    if target==320:
        assert request['approval_snapshot']['factor']=='0.8750'
        assert request['approval_snapshot']['total']=='400.00'
    result=await agent._verify_write_result('apply_price',request,'新報價單: '+new['quotation_number'])
    assert result.verified, result.text
    assert '核對失敗' not in result.text
    assert '符合核准試算結果' in result.text
    if direction:
        assert f'{direction}目標 {gap}' in request['preface']
        assert f'{direction}目標 {gap}' in result.text
        assert '未精確達到指定目標' in result.text
    else:
        assert '實際總價與指定目標相同' in result.text

@pytest.mark.asyncio
@pytest.mark.parametrize('tamper', ['factor','total','profit','source','target','catalog','level'])
async def test_matching_policy_or_near_target_cannot_hide_wrong_approved_result(fake_backend,bundle_path,monkeypatch,tamper):
    request,new=await approved_fixture(fake_backend,bundle_path,monkeypatch)
    if tamper=='factor': new['pricing_factor']='0.9'  # same rounded total, wrong approved factor
    elif tamper=='total': new['total_price']='320'  # meets user target, wrong approved result
    elif tamper=='profit': new['profit_amount']='301'
    elif tamper=='source': request['approval_snapshot']['source']['notes']='tampered'
    elif tamper=='target': request['approval_snapshot']['target_total']=400
    elif tamper=='catalog': new['items'][0]['product_cost']='0.02'
    elif tamper=='level': new['customer_level']='standard'
    result=await agent._verify_write_result('apply_price',request,'新報價單: '+new['quotation_number'])
    assert not result.verified
    assert '核對失敗' in result.text
