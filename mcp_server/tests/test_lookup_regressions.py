import importlib.util
from pathlib import Path
import pytest
import httpx

spec=importlib.util.spec_from_file_location('reviewed_mcp',Path(__file__).resolve().parents[1]/'server.py')
server=importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)

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
