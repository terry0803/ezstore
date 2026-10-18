"""Real A2A -> Agent -> MCP -> PostgreSQL, ONLY against dedicated test ports.

Run with advisor/.venv Python, isolated backend on 58081 and agent on 58511.
No LLM calls; the exact structured request produced by the advisor is used.
"""
import asyncio
import json
from pathlib import Path
import runpy
import sys
import time
from types import SimpleNamespace

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'advisor'))
from pricing_advisor.a2a_client import QuotationAgentClient


async def main():
    compute = runpy.run_path(str(ROOT/'knowledge/ezstore/references/computations/price_change_impact.py'))['compute']
    peer = QuotationAgentClient('http://127.0.0.1:58511/a2a/quotation_agent', timeout=45, poll_interval=.1)
    evidence=[]
    async with httpx.AsyncClient(base_url='http://127.0.0.1:58081/api/v1', timeout=20) as c:
        async def req(method,path,**kw):
            r=await c.request(method,path,**kw); r.raise_for_status(); return r.json()
        key=str(time.time_ns())
        customer=await req('POST','/customers',json={'name':'Atomic approval test','tax_id':key[-8:],'level':'standard'})
        product=await req('POST','/products',json={'product_number':'AT-'+key,'name':'Atomic approval test','cost':'60','list_price':'100','inventory':100})
        async def source():
            return await req('POST','/quotations',json={'customer_id':customer['id'],'pricing_factor':'1','items':[{'product_id':product['id'],'quantity':1}]})
        def envelope(q):
            result=compute(q,100)
            return 'EZSTORE_APPROVED_PRICE_V1\n'+json.dumps({'quotation_number':q['quotation_number'],'target_total_price':100,
                'approval':{'source':q,'target_total':100,'factor':result['new_factor'],'total':result['new_total'],'profit':result['new_profit']}})
        async def count(): return (await req('GET','/quotations'))['total']
        q=await source(); before=await count()
        result=await peer.send(envelope(q))
        assert '新報價單:' in result.text, result.text
        assert await count()==before+1
        assert await req('GET',f"/quotations/{q['id']}")==q
        evidence.append({'case':'real_a2a_atomic_success','task_id':result.task_id,'reply':result.text})
        from pricing_advisor import agent as advisor
        from pricing_advisor.backend import Backend
        advisor.backend=Backend('http://127.0.0.1:58081/api/v1')
        advisor.quotation_agent=peer
        q=await source()
        event=await advisor.apply_price(SimpleNamespace(state={}),{'quotation_number':q['quotation_number'],'target_total':100})
        assert event.actions.route=='delegate', event.output
        assert event.output['approval_snapshot']['source']==q
        before=await count()
        response=await advisor._send_a2a(event.output)
        assert '新報價單:' in response.output and '核對失敗' not in response.output, response.output
        assert await count()==before+1
        evidence.append({'case':'real_advisor_policy_to_a2a_success','reply':response.output})
        q=await source()
        event=await advisor.apply_price(SimpleNamespace(state={}),{'quotation_number':q['quotation_number'],'target_total':100})
        assert event.actions.route=='delegate', event.output
        await req('PUT',f"/quotations/{q['id']}",json={'customer_id':q['customer_id'],'pricing_factor':'1','items':[{'product_id':product['id'],'quantity':2}]})
        before=await count()
        response=await advisor._send_a2a(event.output)
        assert 'APPROVAL_CHANGED' in response.output and '核對失敗' not in response.output, response.output
        assert await count()==before
        evidence.append({'case':'real_advisor_approval_then_edit_rejected','reply':response.output})
        q=await source(); request=envelope(q)
        await req('PUT',f"/quotations/{q['id']}",json={'customer_id':q['customer_id'],'pricing_factor':'1','items':[{'product_id':product['id'],'quantity':2}]})
        before=await count()
        result=await peer.send(request)
        assert 'APPROVAL_CHANGED' in result.text, result.text
        assert '沒有建立副本' in result.text and '可能已經建立' not in result.text
        assert await count()==before
        evidence.append({'case':'real_a2a_quantity_changed_no_draft','task_id':result.task_id,'reply':result.text})
        q=await source(); request=envelope(q)
        await req('PUT',f"/products/{product['id']}",json={**product,'cost':'120'})
        before=await count()
        result=await peer.send(request)
        assert 'APPROVAL_CHANGED' in result.text, result.text
        assert await count()==before
        evidence.append({'case':'real_a2a_catalog_changed_no_draft','task_id':result.task_id,'reply':result.text})
        before=await count()
        result=await peer.send('EZSTORE_APPROVED_PRICE_V1\n{}')
        assert '未送出操作' in result.text
        assert await count()==before
        evidence.append({'case':'malformed_a2a_guard_no_draft','task_id':result.task_id,'reply':result.text})
    print(json.dumps(evidence,ensure_ascii=False,indent=2))
    if len(sys.argv)>1: Path(sys.argv[1]).write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')


if __name__=='__main__': asyncio.run(main())
