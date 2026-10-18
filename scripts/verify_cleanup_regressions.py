"""Conditional compensation tests against ONLY the isolated ezstore-fix-check DB.

Both request orderings exercise real PostgreSQL locks via HTTP, not mocks.
"""
import argparse
import asyncio
import json
from pathlib import Path

import httpx
from verify_concurrency_regressions import hold, blocked
from verify_storage_regressions import BASE


async def run(output):
    results = []

    def passed(case, **evidence):
        results.append({'case': case, 'passed': True, **evidence})
        output.write_text(json.dumps(results, indent=2), encoding='utf-8')
        print('PASS', case, flush=True)

    async with httpx.AsyncClient(base_url=BASE, timeout=40) as c:
        async def req(method, path, **kw):
            r = await c.request(method, path, **kw)
            r.raise_for_status()
            return r.json()

        async def duplicate():
            return await req('POST', '/quotations/9/duplicate')

        async def cleanup(q):
            return await c.delete(f"/quotations/{q['id']}", params={'expected_updated_at': q['updated_at']})

        def order_body(q):
            return {'customer_id': q['customer_id'], 'quotation_id': q['id'],
                    'notes': 'cleanup regression fixture',
                    'items': [{'product_id': 1, 'unit_price': '100', 'quantity': 1}]}

        for mode in ('create', 'relink'):
            for first in ('order', 'cleanup'):
                q = await duplicate()
                body = order_body(q)
                existing = await req('POST', '/orders', json={**body, 'quotation_id': None}) if mode == 'relink' else None

                async def link():
                    return await c.request('PUT' if existing else 'POST',
                                           f"/orders/{existing['id']}" if existing else '/orders', json=body)

                gate = await hold('quotations', q['id'])
                try:
                    if first == 'order':
                        order_task = asyncio.create_task(link())
                        await blocked()
                        cleanup_task = asyncio.create_task(cleanup(q))
                    else:
                        cleanup_task = asyncio.create_task(cleanup(q))
                        await blocked()
                        order_task = asyncio.create_task(link())
                    await blocked(2)
                    order, deleted = await asyncio.gather(order_task, cleanup_task)
                finally:
                    await gate
                fetched = await c.get(f"/quotations/{q['id']}")
                if first == 'order':
                    assert order.status_code in (200, 201), order.text
                    assert deleted.status_code >= 400 and fetched.status_code == 200, (deleted.text, fetched.text)
                    assert fetched.json() == q
                    stored = await req('GET', f"/orders/{order.json()['id']}")
                    assert stored['quotation_id'] == q['id']
                else:
                    assert deleted.status_code == 204 and fetched.status_code == 404, (deleted.text, fetched.text)
                    assert order.status_code == 400, order.text
                    if existing:
                        assert await req('GET', f"/orders/{existing['id']}") == existing
                passed(f'{mode}_{first}_first', quotation_id=q['id'], order_http=order.status_code,
                       cleanup_http=deleted.status_code, quotation_http=fetched.status_code)

        # Version checks and publication guards must survive the locking change.
        for change in ('unchanged', 'edited', 'published'):
            q = await duplicate()
            if change == 'edited':
                await req('PUT', f"/quotations/{q['id']}", json={
                    'customer_id': q['customer_id'], 'pricing_factor': q['pricing_factor'],
                    'notes': 'keep this edit', 'items': [
                        {'product_id': i['product_id'], 'quantity': i['quantity']} for i in q['items']]})
            elif change == 'published':
                await req('POST', f"/quotations/{q['id']}/publish")
            before = await req('GET', f"/quotations/{q['id']}")
            deleted = await cleanup(q)
            if change == 'unchanged':
                assert deleted.status_code == 204, deleted.text
                assert (await c.get(f"/quotations/{q['id']}")).status_code == 404
            else:
                assert deleted.status_code >= 400, deleted.text
                assert await req('GET', f"/quotations/{q['id']}") == before
            passed(f'cleanup_{change}', cleanup_http=deleted.status_code)
    return results


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    asyncio.run(run(parser.parse_args().output))
