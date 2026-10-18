"""Regression acceptance; writes only to the isolated 58080 fixture, never the homework DB."""
import argparse
import asyncio
from pathlib import Path
from verify_live_agents import Acceptance


async def run(output,model):
    t=Acceptance(output,set(),model)
    q='QT-20260325-001';copy='QT-20260330-001'
    async def no_write(app,prompt,expected=()):
        await t.no_write(app,prompt,list(expected))
    async def history():
        s=await t.session('pricing_advisor')
        await t.no_write('pricing_advisor',f'{q} 壓到200000可以嗎？',['試算'],s)
        await t.no_write('pricing_advisor',f'先把 {q} 總價改成2026/10/17',['請提供'],s)
    async def invalid_replacement():
        s=await t.session('pricing_advisor')
        await t.no_write('pricing_advisor',f'{q} 壓到200000可以嗎？',['試算'],s)
        await t.no_write('pricing_advisor',f'幫我把 {q} 總價改到明天',['請提供'],s)
    async def costs():
        response=await t.http.get('http://127.0.0.1:58080/api/v1/products/6')
        response.raise_for_status(); product=response.json()
        original={k:product[k] for k in ('product_number','name','description','cost','list_price','inventory','supplier')}
        response=await t.http.put('http://127.0.0.1:58080/api/v1/products/6',json={**original,'cost':'790'})
        response.raise_for_status()
        try:
            await no_write('pricing_advisor',f'幫我把 {copy} 總價改成8000',['成本或牌價','沒有改資料'])
            await no_write('quotation_agent',f'幫我把 {copy} 總價改成8000',['未送出操作'])
        finally:
            response=await t.http.put('http://127.0.0.1:58080/api/v1/products/6',json=original)
            response.raise_for_status()
    cases=[
        ('first_howto',lambda:no_write('quotation_agent',f'請問如何複製報價單 {copy}')),
        ('advisor_howto',lambda:no_write('pricing_advisor',f'請問如何複製報價單 {copy}')),
        ('advisor_howto_suffix',lambda:no_write('pricing_advisor',f'複製報價單 {copy} 的操作流程是什麼？')),
        ('english_alternatives',lambda:no_write('pricing_advisor',f'Change total of {q} to 200000 or 210000',['請提供'])),
        ('slash_alternatives',lambda:no_write('pricing_advisor',f'把 {q} 總價改成200000 / 210000',['請提供'])),
        ('scientific_amount',lambda:no_write('pricing_advisor',f'把 {q} 總價改成2e5',['請提供'])),
        ('invalid_new_amount_after_check',history),
        ('factor_storage_failure_before_copy',lambda:no_write('quotation_agent',f'把 {copy} 報價因子改成0.0001',['未送出操作','沒有建立副本'])),
        ('catalog_drift_before_copy',costs),
        ('first_effect_question',lambda:no_write('quotation_agent',f'複製報價單 {copy} 會產生哪些資料？')),
        ('advisor_effect_question',lambda:no_write('pricing_advisor',f'複製報價單 {copy} 會產生哪些資料？')),
        ('first_support_question',lambda:no_write('quotation_agent',f'系統支援複製報價單 {copy} 嗎？')),
        ('advisor_past_narration',lambda:no_write('pricing_advisor',f'昨天同事複製了報價單 {copy}，我只是描述這件事。')),
        ('first_describe_conversion',lambda:no_write('quotation_agent',f'請描述將報價單 {copy} 轉訂單的結果。')),
        ('invalid_replacement_after_check',invalid_replacement),
        ('first_stated_price',lambda:no_write('quotation_agent',f'{q} 的總價是200000')),
        ('advisor_stated_price',lambda:no_write('pricing_advisor',f'{q} 的總價是200000')),
        ('first_completed_copy',lambda:no_write('quotation_agent',f'報價單 {copy} 複製完了')),
        ('advisor_completed_copy',lambda:no_write('pricing_advisor',f'報價單 {copy} 複製完了')),
    ]
    try:
        for name,fn in cases:await t.case(name,fn)
        t._save(complete=True,expected_cases=len(cases))
    finally:await t.http.aclose()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--model',required=True)
    args=parser.parse_args()
    asyncio.run(run(args.output,args.model))
