from pathlib import Path
from decimal import Decimal, ROUND_HALF_UP
import httpx,json
OUT=Path(__file__).parent
BASE='http://127.0.0.1:58080/api/v1'
with httpx.Client(base_url=BASE,timeout=20,trust_env=False) as c:
    r=c.get('/quotations/12');r.raise_for_status(); source=r.json()
    item=next(x for x in source['items'] if Decimal(str(x['list_price']))==650)
    payload={'customer_id':source['customer_id'],'pricing_factor':'0.3333','notes':'isolated recheck: monetary rounding','items':[{'product_id':item['product_id'],'quantity':3}]}
    r=c.post('/quotations',json=payload);r.raise_for_status();created=r.json()
    r=c.get('/quotations/'+str(created['id']));r.raise_for_status();stored=r.json()
    row=stored['items'][0]
    expected=Decimal(str(row['unit_price']))*row['quantity']
    result={'isolated_backend':BASE,'request':payload,'created':created,'stored':stored,'unit_price_times_quantity':str(expected),'stored_subtotal':row['subtotal'],'difference':str(Decimal(str(row['subtotal']))-expected),'consistent':expected==Decimal(str(row['subtotal']))}
(OUT/'rounding-probe.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({k:v for k,v in result.items() if k not in ('created','stored','request')},ensure_ascii=False))
