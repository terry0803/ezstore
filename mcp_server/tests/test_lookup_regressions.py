import importlib.util
from pathlib import Path
import pytest

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
