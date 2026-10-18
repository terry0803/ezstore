"""Destructive fixture tests ONLY for the isolated ezstore-fix-check stack.

Uses real HTTP writes and PostgreSQL row locks to reproduce request interleavings.
Never connects to the normal homework database. Run after isolated services start.
"""
import argparse
import asyncio
import json
from decimal import Decimal
from pathlib import Path

import httpx
from verify_storage_regressions import BASE, sql, wait_sql


async def blocked(count=1):
    await wait_sql("SELECT CASE WHEN (SELECT count(*) FROM pg_stat_activity "
                   "WHERE pid<>pg_backend_pid() AND wait_event_type='Lock') >= "
                   f"{count} THEN 1 ELSE 0 END")


async def hold(table, row_id):
    assert table in ('orders', 'quotations')
    task = asyncio.create_task(asyncio.to_thread(sql,
        f"BEGIN; SELECT id FROM {table} WHERE id={int(row_id)} FOR UPDATE; "
        "SELECT pg_sleep(8) /* concurrency_regression_gate */; COMMIT;"))
    await wait_sql("SELECT CASE WHEN EXISTS (SELECT 1 FROM pg_stat_activity "
        "WHERE pid<>pg_backend_pid() AND query LIKE '%concurrency_regression_gate%' "
        "AND wait_event='PgSleep') THEN 1 ELSE 0 END")
    return task


async def run(output):
    results = []

    def passed(case, **evidence):
        results.append({'case': case, 'passed': True, **evidence})
        output.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
        print('PASS', case, flush=True)

    async with httpx.AsyncClient(base_url=BASE, timeout=40) as c:
        async def req(method, path, **kw):
            response = await c.request(method, path, **kw)
            response.raise_for_status()
            return response.json()

        async def duplicate():
            return await req('POST', '/quotations/9/duplicate')

        def qi(q, customer):
            return {'customer_id': customer, 'pricing_factor': q['pricing_factor'],
                    'notes': 'concurrency regression fixture',
                    'items': [{'product_id': i['product_id'], 'quantity': i['quantity']} for i in q['items']]}

        def oi(customer, quantity=1):
            return {'customer_id': customer, 'notes': 'concurrency regression fixture',
                    'items': [{'product_id': 1, 'unit_price': '100', 'quantity': quantity}]}

        q = await duplicate()
        o = await req('POST', '/orders', json={**oi(q['customer_id']), 'quotation_id': q['id']})
        rejected = await c.put(f"/quotations/{q['id']}", json=qi(q, 15))
        assert rejected.status_code == 400 and '不可更換客戶' in rejected.text, rejected.text
        assert await req('GET', f"/quotations/{q['id']}") == q
        assert (await req('GET', f"/orders/{o['id']}"))['customer_id'] == q['customer_id']
        # Existing associations must not prevent an ordinary same-customer edit.
        same = await req('PUT', f"/quotations/{q['id']}", json=qi(q, q['customer_id']))
        assert same['notes'] == 'concurrency regression fixture'
        passed('linked_quote_customer_change_rejected', quotation_id=q['id'], order_id=o['id'])

        # Both directions: whichever operation obtains the quotation lock first
        # determines which other operation must be rejected. Test create AND relink.
        for mode in ('create', 'relink'):
            for first in ('quote', 'order'):
                q = await duplicate()
                body = {**oi(q['customer_id']), 'quotation_id': q['id']}
                existing = await req('POST', '/orders', json=oi(q['customer_id'])) if mode == 'relink' else None
                async def order_request():
                    if existing:
                        return await c.put(f"/orders/{existing['id']}", json=body)
                    return await c.post('/orders', json=body)
                lock = await hold('quotations', q['id'])
                try:
                    if first == 'quote':
                        change = asyncio.create_task(c.put(f"/quotations/{q['id']}", json=qi(q, 15)))
                        await blocked()
                        link = asyncio.create_task(order_request())
                    else:
                        link = asyncio.create_task(order_request())
                        await blocked()
                        change = asyncio.create_task(c.put(f"/quotations/{q['id']}", json=qi(q, 15)))
                    await blocked(2)
                    changed, linked = await asyncio.gather(change, link)
                finally:
                    await lock
                if first == 'quote':
                    assert changed.status_code == 200 and linked.status_code == 400, (changed.text, linked.text)
                    if existing:
                        assert await req('GET', f"/orders/{existing['id']}") == existing
                else:
                    assert linked.status_code in (200, 201) and changed.status_code == 400, (changed.text, linked.text)
                    saved_q = await req('GET', f"/quotations/{q['id']}")
                    saved_o = await req('GET', f"/orders/{linked.json()['id']}")
                    assert saved_q['customer_id'] == saved_o['customer_id']
                passed(f'{mode}_vs_customer_change_{first}_first', change_http=changed.status_code, order_http=linked.status_code)

        q = await duplicate()
        lock = await hold('quotations', q['id'])
        try:
            publish = asyncio.create_task(c.post(f"/quotations/{q['id']}/publish"))
            await blocked()
            delete = asyncio.create_task(c.delete(f"/quotations/{q['id']}"))
            await blocked(2)
            pr, dr = await asyncio.gather(publish, delete)
        finally:
            await lock
        assert pr.status_code == 200 and dr.status_code == 403, (pr.text, dr.text)
        saved = await req('GET', f"/quotations/{q['id']}")
        assert saved['status'] == 'published' and saved['items'] == q['items']
        draft = await duplicate()
        assert (await c.delete(f"/quotations/{draft['id']}")).status_code == 204
        passed('publish_blocks_stale_delete', quotation_id=q['id'], delete_http=dr.status_code)

        o = await req('POST', '/orders', json=oi(5))
        lock = await hold('orders', o['id'])
        try:
            first = asyncio.create_task(c.put(f"/orders/{o['id']}", json=oi(5, 2)))
            await blocked()
            second = asyncio.create_task(c.put(f"/orders/{o['id']}", json=oi(5, 3)))
            await blocked(2)
            r1, r2 = await asyncio.gather(first, second)
        finally:
            await lock
        assert r1.status_code == r2.status_code == 200, (r1.text, r2.text)
        saved = await req('GET', f"/orders/{o['id']}")
        item_sum = sum(Decimal(i['subtotal']) for i in saved['items'])
        assert len(saved['items']) == 1 and saved['items'][0]['quantity'] in (2, 3), saved
        assert item_sum == Decimal(saved['total_price']), saved
        passed('concurrent_order_edits_remain_consistent', order_id=o['id'], total=saved['total_price'], item_sum=str(item_sum))
    return results


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    asyncio.run(run(args.output))
