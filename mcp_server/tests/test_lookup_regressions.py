import importlib.util
from pathlib import Path
import pytest
import httpx

spec=importlib.util.spec_from_file_location('reviewed_mcp',Path(__file__).resolve().parents[1]/'server.py')
server=importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)


@pytest.mark.asyncio
@pytest.mark.parametrize('reject', [False, True])
async def test_guarded_price_uses_one_atomic_request_and_never_falls_back(monkeypatch, reject):
    import runpy
    q = {'id':1,'quotation_number':'QT-20260330-001','customer_id':1,'customer_level':'standard',
         'pricing_factor':'1','items':[{'product_id':1,'list_price':'100','product_cost':'60','quantity':1,'unit_price':'100'}]}
    compute = runpy.run_path(str(Path(__file__).resolve().parents[2]/'knowledge/ezstore/references/computations/price_change_impact.py'))['compute']
    result = compute(q,100)
    approval = {'source':q,'target_total':100,'factor':result['new_factor'],'total':result['new_total'],'profit':result['new_profit']}
    calls=[]
    async def post(path, body):
        calls.append((path,body))
        if reject: raise server.ToolError('APPROVAL_CHANGED')
        return {**q,'id':2,'quotation_number':'QT-20261018-999','total_price':result['new_total']}
    async def forbidden(*args, **kw): pytest.fail('guard must not call ordinary duplicate/update or reload approval')
    monkeypatch.setattr(server,'_post',post)
    monkeypatch.setattr(server,'_put',forbidden)
    monkeypatch.setattr(server,'_require_quotation',forbidden)
    if reject:
        with pytest.raises(server.ToolError,match='APPROVAL_CHANGED'):
            await server.adjust_total_price(q['quotation_number'],100,approval)
    else:
        reply=await server.adjust_total_price(q['quotation_number'],100,approval)
        assert 'QT-20261018-999' in reply
    assert calls == [('/quotations/1/approved-price-copy',approval)]


@pytest.mark.asyncio
@pytest.mark.parametrize('change',['factor','total','profit','target_total','source'])
async def test_guarded_price_rejects_inconsistent_approval_before_http(monkeypatch, change):
    approval={'source':{'id':1,'quotation_number':'QT-20260330-001','items':[{'list_price':'100','product_cost':'60','quantity':1}]},
              'target_total':100,'factor':'1','total':'100','profit':'40'}
    approval[change] = {} if change=='source' else '999'
    async def forbidden(*args,**kw): pytest.fail('invalid approval must not write')
    monkeypatch.setattr(server,'_post',forbidden)
    with pytest.raises(server.ToolError,match='沒有建立副本'):
        await server.adjust_total_price('QT-20260330-001',100,approval)


@pytest.mark.asyncio
@pytest.mark.parametrize('rows,target', [
    ([('0.04', 100000)], 3000),
    ([('0.01', 1000)], 5),
    ([('650', 3)], 649.95),
    ([('1', 3)], 3.015),
    ([('120000', 2), ('18000', 1)], 180000),
    ([('0.04', 100000), ('3.57', 123)], 3500),
    ([('650', 10)], 100000),
    ([('650', 10)], 1),
])
async def test_attested_prediction_matches_real_mcp_search(monkeypatch, rows, target):
    from contextlib import asynccontextmanager
    from decimal import Decimal, ROUND_HALF_UP
    import runpy
    compute = runpy.run_path(str(Path(__file__).resolve().parents[2] / 'knowledge/ezstore/references/computations/price_change_impact.py'))['compute']
    items = [{'product_id':i+1,'list_price':price,'product_cost':'0','quantity':qty,'unit_price':price} for i,(price,qty) in enumerate(rows)]
    q = {'id':1,'customer_id':1,'quotation_number':'QT-20260330-001','pricing_factor':'1','items':items}
    predicted = compute(q,target)
    writes = []
    async def require(_number):
        return q
    @asynccontextmanager
    async def editing(_q):
        yield {**q,'id':2,'quotation_number':'QT-20261018-999'}
    async def put(_path, payload, **kwargs):
        factor = Decimal(str(payload['pricing_factor']))
        total = sum((Decimal(price)*factor).quantize(Decimal('0.01'), ROUND_HALF_UP)*qty for price,qty in rows)
        writes.append((factor,total))
        return {**q,'id':2,'pricing_factor':str(factor),'total_price':str(total)}
    monkeypatch.setattr(server,'_require_quotation',require)
    monkeypatch.setattr(server,'_editing_copy',editing)
    monkeypatch.setattr(server,'_put',put)
    await server.adjust_total_price(q['quotation_number'],target)
    assert Decimal(predicted['new_factor']) == writes[-1][0]
    assert Decimal(predicted['new_total']) == writes[-1][1]

@pytest.mark.asyncio
async def test_ambiguous_customer_does_not_choose_first(monkeypatch):
    async def get(*args,**kwargs):
        return {'data':[{'id':1,'name':'共同甲公司'},{'id':2,'name':'共同乙公司'}],'total':2}
    monkeypatch.setattr(server,'_get',get)
    with pytest.raises(server.ToolError,match='多位|多個|多筆|不只|符合|找到'):
        await server._find_customer_by_name('共同')
    assert (await server._find_customer_by_name('共同乙公司'))['id']==2

@pytest.mark.asyncio
async def test_reads_all_101_quotes_not_just_first_100(monkeypatch):
    seen=[]
    async def get(path,**params):
        if path=='/customers':return {'data':[{'id':1,'name':'客戶甲'}],'total':1}
        page=params['page'];seen.append(page)
        ids=range(1,101) if page==1 else [101]
        return {'data':[{'id':i,'quotation_number':f'Q{i}','total_price':'100','status':'draft'} for i in ids],'total':101}
    monkeypatch.setattr(server,'_get',get)
    result=await server.list_customer_quotations('客戶甲')
    assert '共 101 筆' in result and 'Q101' in result
    assert seen==[1,2]

@pytest.mark.asyncio
async def test_non_progressing_pagination_fails_instead_of_looping(monkeypatch):
    calls=[]
    async def get(path,**params):
        calls.append(params['page'])
        return {'data':[{'id':1}],'total':101}
    monkeypatch.setattr(server,'_get',get)
    with pytest.raises(server.ToolError,match='沒有完整載入'):
        await server._all_rows('/quotations')
    assert calls==[1,2]


@pytest.mark.asyncio
@pytest.mark.parametrize('factor', [0.00001, 0.00004, 10.0, 12.5, 9.99995, 1e100, float('inf'), float('nan')])
async def test_out_of_range_factor_is_rejected_before_duplicating(monkeypatch, factor):
    """直接呼叫 MCP 也不會留下多的草稿：存不下的報價因子在複製之前就擋。"""
    calls = []

    async def record(*args, **kwargs):
        calls.append(args)
        return {'id': 1, 'customer_id': 1, 'items': []}

    monkeypatch.setattr(server, '_require_quotation', record)
    monkeypatch.setattr(server, '_duplicate', record)
    monkeypatch.setattr(server, '_put', record)
    with pytest.raises(server.ToolError, match='9.9999'):
        await server.update_pricing_factor('QT-TEST-001', factor)
    assert calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize('factor', [0.00005, 0.0001, 9.9999, 9.99994])
async def test_storable_factor_still_duplicates_then_updates(monkeypatch, factor):
    writes = []

    async def require(_number):
        return {'id': 12, 'pricing_factor': '0.9', 'total_price': '90'}

    async def duplicate(q):
        writes.append('duplicate')
        return {'id': 13, 'customer_id': 7, 'notes': '', 'items': [{'product_id': 3, 'quantity': 1}]}

    async def put(path, body):
        writes.append(body['pricing_factor'])
        return {'id': 13, 'quotation_number': 'QT-TEST-002', 'pricing_factor': '9.9999', 'total_price': '999.99'}

    monkeypatch.setattr(server, '_require_quotation', require)
    monkeypatch.setattr(server, '_duplicate', duplicate)
    monkeypatch.setattr(server, '_put', put)
    await server.update_pricing_factor('QT-TEST-001', factor)
    assert writes == ['duplicate', factor]


@pytest.mark.asyncio
@pytest.mark.parametrize('operation,fail_at', [('update_pricing_factor', 1), ('adjust_total_price', 1), ('adjust_total_price', 3)])
@pytest.mark.parametrize('failure', ['rejected', 'timeout', 'cleanup_failed', 'malformed', 'gateway_timeout'])
async def test_failed_adjustment_cleans_only_acknowledged_draft_or_reports_its_link(monkeypatch, operation, fail_at, failure):
    source = {'id': 1, 'quotation_number': 'QT-20260330-001', 'pricing_factor': '1', 'total_price': '100'}
    draft = {'id': 2, 'quotation_number': 'QT-20261018-001', 'customer_id': 1, 'notes': '',
             'items': [{'product_id': 1, 'quantity': 1}], 'updated_at': '2026-10-18T00:00:00Z'}
    calls = []
    attempts = 0

    async def require(_):
        return source.copy()

    async def duplicate(q):
        assert q == source
        calls.append('duplicate')
        return draft.copy()

    async def put(path, data, **kwargs):
        nonlocal attempts
        attempts += 1
        calls.append('put')
        assert path == '/quotations/2'
        if attempts == fail_at:
            if failure == 'timeout':
                raise server.ToolError('後端服務逾時') from httpx.ReadTimeout('response lost')
            if failure == 'malformed':
                raise server.ToolError('後端回覆格式異常') from ValueError('invalid JSON')
            if failure == 'gateway_timeout':
                response = httpx.Response(504, request=httpx.Request('PUT', 'http://test/quotations/2'))
                raise server.ToolError('後端回應 504') from httpx.HTTPStatusError('gateway timeout', request=response.request, response=response)
            raise server.ToolError('後端回應 400：無效資料')
        return {**draft, 'total_price': '1', 'updated_at': f'2026-10-18T00:00:0{attempts}Z'}

    async def request(method, path, **kwargs):
        calls.append('delete')
        assert (method, path) == ('DELETE', '/quotations/2')
        stamp = draft['updated_at'] if fail_at == 1 else f'2026-10-18T00:00:0{fail_at-1}Z'
        assert kwargs['params'] == {'expected_updated_at': stamp}
        if failure == 'cleanup_failed':
            raise server.ToolError('副本已變更或清理失敗')
        return {}

    monkeypatch.setattr(server, '_require_quotation', require)
    monkeypatch.setattr(server, '_duplicate', duplicate)
    monkeypatch.setattr(server, '_put', put)
    monkeypatch.setattr(server, '_request', request)
    with pytest.raises(server.ToolError) as caught:
        await getattr(server, operation)(source['quotation_number'], 1.2 if operation == 'update_pricing_factor' else 210000)
    message = str(caught.value)
    assert '原始報價單: QT-20260330-001（未修改）' in message
    assert calls.count('duplicate') == 1 and calls.count('put') == fail_at
    if failure == 'rejected':
        assert '本次失敗副本已移除' in message
        assert calls[-1] == 'delete'
    else:
        assert '待確認副本: QT-20261018-001' in message
        assert '/quotations/2' in message and '勿直接重試' in message
        if failure in ('timeout', 'malformed', 'gateway_timeout'):
            assert 'delete' not in calls


@pytest.mark.asyncio
@pytest.mark.parametrize('value', [float('nan'), float('inf'), -1, 0])
async def test_invalid_target_never_creates_a_copy(monkeypatch, value):
    async def forbidden(*args):
        raise AssertionError('must reject before reading or copying')
    monkeypatch.setattr(server, '_require_quotation', forbidden)
    with pytest.raises(server.ToolError, match='有限數值'):
        await server.adjust_total_price('QT-20260330-001', value)


@pytest.mark.asyncio
async def test_delete_accepts_empty_204_response(monkeypatch):
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(204)), base_url='http://test') as client:
        monkeypatch.setattr(server, '_client', client)
        assert await server._request('DELETE', '/quotations/2') == {}
