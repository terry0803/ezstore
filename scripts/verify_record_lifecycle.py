"""Real-DB lifecycle regressions, ONLY on the isolated ezstore-fix-check stack."""
import argparse
import asyncio
import json
import time
from pathlib import Path

import httpx
from verify_storage_regressions import BASE, sql, wait_sql
from verify_concurrency_regressions import blocked, hold


async def hold_record(table, row_id):
    assert table in ('customers', 'products')
    task = asyncio.create_task(asyncio.to_thread(sql,
        f"BEGIN; SELECT id FROM {table} WHERE id={int(row_id)} FOR UPDATE; "
        "SELECT pg_sleep(8) /* lifecycle_regression_gate */; COMMIT;"))
    await wait_sql("SELECT CASE WHEN EXISTS (SELECT 1 FROM pg_stat_activity "
                   "WHERE pid<>pg_backend_pid() AND query LIKE '%lifecycle_regression_gate%' "
                   "AND wait_event='PgSleep') THEN 1 ELSE 0 END")
    return task


async def run(output):
    results = []

    def passed(case, **evidence):
        results.append({'case': case, 'passed': True, **evidence})
        output.write_text(json.dumps(results, indent=2), encoding='utf-8')
        print('PASS', case, flush=True)

    async with httpx.AsyncClient(base_url=BASE, timeout=40) as c:
        async def req(method, path, **kw):
            response = await c.request(method, path, **kw)
            response.raise_for_status()
            return response.json()

        for kind in ('customers', 'products'):
            for first in ('delete', 'update'):
                stamp = str(time.time_ns())
                body = ({'name': 'Lifecycle customer', 'tax_id': stamp[-8:], 'level': 'standard',
                         'credit_score': 80, 'contact_name': 'Old contact'} if kind == 'customers' else
                        {'name': 'Lifecycle product', 'product_number': 'LIFECYCLE-' + stamp,
                         'cost': '40', 'list_price': '100', 'inventory': 3, 'supplier': 'Old supplier'})
                record = await req('POST', '/' + kind, json=body)
                path = f"/{kind}/{record['id']}"
                gate = await hold_record(kind, record['id'])
                try:
                    if first == 'delete':
                        deleting = asyncio.create_task(c.delete(path))
                        await blocked()
                        updating = asyncio.create_task(c.put(path, json={**body, 'name': 'Queued edit'}))
                    else:
                        updating = asyncio.create_task(c.put(path, json={**body, 'name': 'Queued edit'}))
                        await blocked()
                        deleting = asyncio.create_task(c.delete(path))
                    await blocked(2)
                    deleted, updated = await asyncio.gather(deleting, updating)
                finally:
                    await gate
                assert deleted.status_code == 204, deleted.text
                assert updated.status_code == (400 if first == 'delete' else 200), updated.text
                assert (await c.get(path)).status_code == 404
                assert (await c.put(path, json=body)).status_code == 400
                assert (await c.get(path)).status_code == 404
                passed(f'{kind}_{first}_first_stays_deleted', id=record['id'],
                       delete_http=deleted.status_code, update_http=updated.status_code)

            # Replacing Save must still persist zero and empty values correctly.
            body = {**body, 'tax_id': str(time.time_ns())[-8:]} if kind == 'customers' else {
                **body, 'product_number': 'LIFECYCLE-ZERO-' + str(time.time_ns())}
            record = await req('POST', '/' + kind, json=body)
            # Compare persisted timestamps: POST returns nanoseconds before PostgreSQL
            # normalizes them to microseconds.
            record = await req('GET', f"/{kind}/{record['id']}")
            zeros = {'credit_score': 0, 'contact_name': ''} if kind == 'customers' else {
                'cost': '0', 'list_price': '0', 'inventory': 0, 'supplier': ''}
            changed = await req('PUT', f"/{kind}/{record['id']}", json={**body, **zeros})
            stored = await req('GET', f"/{kind}/{record['id']}")
            assert all(stored[key] == value for key, value in zeros.items()), stored
            assert stored['id'] == record['id'] and stored['created_at'] == record['created_at']
            assert stored['deleted_at'] is None and changed['updated_at'] >= record['updated_at']
            passed(f'{kind}_zero_and_empty_values_persist')

        async def duplicate():
            return await req('POST', '/quotations/9/duplicate')

        def order_body(q):
            return {'customer_id': q['customer_id'], 'quotation_id': q['id'],
                    'items': [{'product_id': 1, 'quantity': 1, 'unit_price': '100'}]}

        for mode in ('create', 'relink'):
            for first in ('order', 'delete'):
                q = await duplicate()
                body = order_body(q)
                existing = await req('POST', '/orders', json={**body, 'quotation_id': None}) if mode == 'relink' else None

                async def link():
                    return await c.request('PUT' if existing else 'POST',
                        f"/orders/{existing['id']}" if existing else '/orders', json=body)

                gate = await hold('quotations', q['id'])
                try:
                    if first == 'order':
                        linking = asyncio.create_task(link())
                        await blocked()
                        deleting = asyncio.create_task(c.delete(f"/quotations/{q['id']}"))
                    else:
                        deleting = asyncio.create_task(c.delete(f"/quotations/{q['id']}"))
                        await blocked()
                        linking = asyncio.create_task(link())
                    await blocked(2)
                    linked, deleted = await asyncio.gather(linking, deleting)
                finally:
                    await gate
                if first == 'order':
                    assert linked.status_code in (200, 201) and deleted.status_code == 409, (linked.text, deleted.text)
                    assert await req('GET', f"/quotations/{q['id']}") == q
                    stored = await req('GET', f"/orders/{linked.json()['id']}")
                    assert stored['quotation_id'] == q['id']
                else:
                    assert deleted.status_code == 204 and linked.status_code == 400, (linked.text, deleted.text)
                    assert (await c.get(f"/quotations/{q['id']}")).status_code == 404
                    if existing:
                        assert await req('GET', f"/orders/{existing['id']}") == existing
                passed(f'ordinary_delete_{mode}_{first}_first', quotation_id=q['id'],
                       order_http=linked.status_code, delete_http=deleted.status_code)

        q = await duplicate()
        order = await req('POST', '/orders', json=order_body(q))
        rejected = await c.delete(f"/quotations/{q['id']}")
        assert rejected.status_code == 409 and '已關聯訂單' in rejected.text
        assert await req('GET', f"/quotations/{q['id']}") == q
        assert (await c.delete(f"/orders/{order['id']}")).status_code == 204
        assert (await c.delete(f"/quotations/{q['id']}")).status_code == 204
        passed('linked_draft_blocked_until_order_deleted')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    asyncio.run(run(parser.parse_args().output))
