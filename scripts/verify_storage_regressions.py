"""Real-DB regressions, restricted to the isolated ezstore-fix-check stack.

Creates fixture quotes/orders; never connects to the regular homework service.
Run with advisor/.venv Python while the isolated stack is healthy.
"""
import argparse
import asyncio
import json
import subprocess
from pathlib import Path

import httpx

BASE = 'http://127.0.0.1:58080/api/v1'
DB = 'ezstore-fix-check-db-1'


def sql(query):
    return subprocess.check_output(
        ['docker', 'exec', DB, 'psql', '-U', 'ezstore', '-d', 'ezstore', '-At', '-c', query],
        text=True, encoding='utf-8', timeout=30).strip()


async def wait_sql(query):
    for _ in range(100):
        if await asyncio.to_thread(sql, query) == '1':
            return
        await asyncio.sleep(.05)
    raise AssertionError('Could not establish the intended concurrent request ordering')


async def run():
    results = []
    async with httpx.AsyncClient(base_url=BASE, timeout=30) as client:
        async def request(method, path, **kwargs):
            response = await client.request(method, path, **kwargs)
            response.raise_for_status()
            return response.json()

        async def duplicate():
            return await request('POST', '/quotations/9/duplicate')

        def quote_input(q, customer):
            return {'customer_id': customer, 'pricing_factor': q['pricing_factor'],
                    'notes': 'storage regression fixture',
                    'items': [{'product_id': i['product_id'], 'quantity': i['quantity']} for i in q['items']]}

        q = await duplicate()
        old_customer = q['customer_id']
        customer = await request('GET', '/customers/15')
        assert old_customer != customer['id']
        changed = await request('PUT', f"/quotations/{q['id']}", json=quote_input(q, customer['id']))
        stored = await request('GET', f"/quotations/{q['id']}")
        for row in (changed, stored):
            assert row['customer_id'] == row['customer']['id'] == customer['id'], row
            assert row['customer_level'] == row['customer']['level'] == customer['level'], row
            assert len(row['items']) == len(q['items'])
        results.append({'case': 'quotation_customer_reassignment', 'passed': True, 'id': q['id']})

        order_body = {'customer_id': old_customer, 'notes': 'storage regression fixture',
                      'items': [{'product_id': i['product_id'], 'unit_price': i['unit_price'],
                                 'quantity': i['quantity']} for i in q['items']]}
        order = await request('POST', '/orders', json=order_body)
        order_body.update(customer_id=customer['id'], quotation_id=q['id'])
        await request('PUT', f"/orders/{order['id']}", json=order_body)
        stored = await request('GET', f"/orders/{order['id']}")
        assert stored['customer_id'] == stored['customer']['id'] == customer['id'], stored
        assert stored['quotation_id'] == q['id']
        assert len(stored['items']) == len(order_body['items'])
        # An invalid cross-customer association must still be rejected.
        bad = dict(order_body, customer_id=old_customer)
        rejected = await client.put(f"/orders/{order['id']}", json=bad)
        assert rejected.status_code >= 400
        assert await request('GET', f"/orders/{order['id']}") == stored
        results.append({'case': 'order_customer_and_quote_agree', 'passed': True, 'id': order['id']})

        q = await duplicate()
        qid = q['id']
        # Hold the row so publish and update both initially see draft. The lock
        # only delays scheduling; all tested mutations use the actual HTTP API.
        lock = asyncio.create_task(asyncio.to_thread(sql,
            f"BEGIN; SELECT id FROM quotations WHERE id={qid} FOR UPDATE; "
            "SELECT pg_sleep(8) /* storage_regression_lock */; COMMIT;"))
        try:
            await wait_sql("SELECT CASE WHEN EXISTS (SELECT 1 FROM pg_stat_activity "
                "WHERE pid<>pg_backend_pid() AND query LIKE '%storage_regression_lock%' "
                "AND wait_event='PgSleep') THEN 1 ELSE 0 END")
            publish = asyncio.create_task(client.post(f'/quotations/{qid}/publish'))
            await wait_sql("SELECT CASE WHEN EXISTS (SELECT 1 FROM pg_stat_activity "
                "WHERE pid<>pg_backend_pid() AND wait_event_type='Lock' "
                "AND query LIKE 'UPDATE%quotations%status%') THEN 1 ELSE 0 END")
            update = asyncio.create_task(client.put(f'/quotations/{qid}', json=quote_input(q, q['customer_id'])))
            published, updated = await asyncio.gather(publish, update)
        finally:
            await lock
        assert published.status_code == 200, published.text
        assert updated.status_code >= 400, updated.text
        final = await request('GET', f'/quotations/{qid}')
        assert final['status'] == 'published' and final['notes'] == q['notes'], final
        assert final['items'] == q['items'], 'Rejected update changed items'
        results.append({'case': 'publish_wins_over_stale_edit', 'passed': True,
                        'id': qid, 'update_status': updated.status_code})
    return results


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = asyncio.run(run())
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False))
