import asyncio,json,sys
from pathlib import Path
from decimal import Decimal
import httpx
from google.adk.tools.mcp_tool import McpToolset
from google.adk.tools.mcp_tool.mcp_session_manager import StreamableHTTPConnectionParams

ROOT=Path('D:/筆電2/資料探勘第一次作業/ezstore')
sys.path.insert(0,str(ROOT/'scripts'))
from verify_live_agents import Acceptance
OUT=Path(__file__).parent

async def main():
    a=Acceptance(OUT/'api-state.json',set(),'no-model')
    rows=[]
    async def request(method,path,payload=None):
        r=await a.http.request(method,'http://127.0.0.1:58080/api/v1'+path,json=payload)
        r.raise_for_status();return r.json()
    q=await a.quote()
    payload={'customer_id':q['customer_id'],'pricing_factor':'1.23456','items':[{'product_id':i['product_id'],'quantity':i['quantity']} for i in q['items']]}
    created=await request('POST','/quotations',payload)
    assert Decimal(created['pricing_factor'])==Decimal('1.2346')
    total=sum(Decimal(i['list_price'])*Decimal('1.2346')*i['quantity'] for i in created['items'])
    assert Decimal(created['total_price'])==total.quantize(Decimal('.01'))
    rows.append({'test':'factor_precision_matches_calculation','passed':True,'id':created['id'],'factor':created['pricing_factor'],'total':created['total_price']})
    before=await a.snapshot()
    for value in ['-1','0','0.00001','10','999999999999']:
        for method,path in [('POST','/quotations'),('PUT',f"/quotations/{created['id']}")]:
            r=await a.http.request(method,'http://127.0.0.1:58080/api/v1'+path,json={**payload,'pricing_factor':value})
            assert r.status_code==400,(value,r.status_code,r.text)
            rows.append({'test':'invalid_factor','method':method,'value':value,'status':r.status_code,'passed':True})
    assert before==await a.snapshot()
    rows.append({'test':'invalid_factors_leave_database_identical','passed':True})
    # Only this isolated stack receives these synthetic customers and copies.
    for i,name in enumerate(['修正測試甲公司','修正測試乙公司']):
        await request('POST','/customers',{'name':name,'tax_id':f'8899000{i}','level':'standard','contact_name':'test','contact_phone':'000','contact_email':'test@example.invalid','address':'test'})
    tools=McpToolset(connection_params=StreamableHTTPConnectionParams(url='http://127.0.0.1:58010/mcp',timeout=30))
    try:
        lookup=next(t for t in await tools.get_tools() if t.name=='list_customer_quotations')
        ambiguous=await lookup.run_async(args={'customer_name':'修正測試'},tool_context=None)
        assert ambiguous.get('isError') is True,ambiguous
        rows.append({'test':'ambiguous_customer_does_not_choose_first','passed':True,'response':ambiguous})
        exact=await lookup.run_async(args={'customer_name':'修正測試乙公司'},tool_context=None)
        assert not exact.get('isError'),exact
        rows.append({'test':'unique_exact_customer_accepted','passed':True,'response':exact})
        for _ in range(101):await request('POST',f"/quotations/{q['id']}/duplicate")
        listing=await request('GET',f"/quotations?customer_id={q['customer_id']}&page_size=100")
        answer=await lookup.run_async(args={'customer_name':q['customer']['name']},tool_context=None)
        body='\n'.join(p.get('text','') for p in answer.get('content',[]))
        assert f"共 {listing['total']} 筆" in body and listing['total']>100,body
        assert body.count('連結:')==listing['total']
        rows.append({'test':'live_mcp_all_pages','passed':True,'actual':listing['total'],'reported_lines':body.count('連結:')})
    finally:
        await tools.close();await a.http.aclose()
    (OUT/'api-check.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'passed':len(rows),'total':len(rows)},ensure_ascii=False))

asyncio.run(main())
