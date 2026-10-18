"""Read-only validation before invoking the instructor's MCP write workflow.

This does not replace MCP writes or its required bisection algorithm. It rejects
inputs known to overflow the supplied schema before a draft can be created.
"""
from decimal import Decimal, ROUND_HALF_UP
import os

import httpx


class PreflightError(ValueError):
    pass


async def _get(path, **params):
    base = os.getenv("BACKEND_API", "http://localhost:8080/api/v1").rstrip("/")
    async with httpx.AsyncClient(base_url=base, timeout=15) as client:
        response = await client.get(path, params=params)
        response.raise_for_status()
        return response.json()


def _check_storage(items, factor):
    total, cost = Decimal(0), Decimal(0)
    for item in items:
        price = (Decimal(str(item["list_price"])) * factor).quantize(Decimal('.01'), rounding=ROUND_HALF_UP)
        subtotal = price * item["quantity"]
        if abs(price.quantize(Decimal('.01'), rounding=ROUND_HALF_UP)) >= Decimal('1e10'):
            raise PreflightError("改價後的單價超過系統可儲存範圍，沒有建立副本")
        if abs(subtotal.quantize(Decimal('.01'), rounding=ROUND_HALF_UP)) >= Decimal('1e12'):
            raise PreflightError("改價後的小計超過系統可儲存範圍，沒有建立副本")
        total += subtotal
        cost += Decimal(str(item["product_cost"])) * item["quantity"]
    if any(abs(value.quantize(Decimal('.01'), rounding=ROUND_HALF_UP)) >= Decimal('1e12')
           for value in (total, total - cost)):
        raise PreflightError("改價後的總價或利潤超過系統可儲存範圍，沒有建立副本")
    rate = (total - cost) / total if total else Decimal(0)
    if abs(rate.quantize(Decimal('.0001'), rounding=ROUND_HALF_UP)) > Decimal('9.9999'):
        raise PreflightError("改價後的利潤率超過系統可儲存範圍，請提高目標價格；沒有建立副本")
    return total.quantize(Decimal('.01'), rounding=ROUND_HALF_UP)


async def validate_change(operation, args):
    try:
        listing = await _get('/quotations', quotation_number=args['quotation_number'], page_size=1)
        rows = listing.get('data') or []
        if not rows or rows[0]['quotation_number'] != args['quotation_number']:
            raise PreflightError("找不到報價單編號 " + args['quotation_number'])
        quotation = await _get(f"/quotations/{rows[0]['id']}")
        current_level = (quotation.get('customer') or {}).get('level')
        if current_level and current_level != quotation.get('customer_level'):
            raise PreflightError("客戶等級已變更，請先建立最新報價再改價；沒有建立副本")
        items = quotation.get('items') or []
        if not items:
            raise PreflightError("報價單沒有品項，沒有建立副本")
        for item in items:
            product = await _get(f"/products/{item['product_id']}")
            if (Decimal(str(product['cost'])) != Decimal(str(item['product_cost']))
                    or Decimal(str(product['list_price'])) != Decimal(str(item['list_price']))):
                raise PreflightError("商品成本或牌價已變更，請先建立最新報價再改價；沒有建立副本")
        result = dict(args)
        if operation == 'update_pricing_factor':
            factor = Decimal(str(args['new_pricing_factor'])).quantize(Decimal('.0001'), rounding=ROUND_HALF_UP)
            if not Decimal(0) < factor <= Decimal('9.9999'):
                raise PreflightError("報價因子超過系統可儲存範圍，沒有建立副本")
            _check_storage(items, factor)
            result['new_pricing_factor'] = float(factor)
        else:
            # Check every candidate the supplied MCP bisection would write.
            lo, hi = .01, 5.0
            target = Decimal(str(args['target_total_price']))
            for _ in range(20):
                mid = (lo + hi) / 2
                total = _check_storage(items, Decimal(str(round(mid, 4))))
                if abs(total - target) < Decimal('.01'):
                    break
                if total < target:
                    lo = mid
                else:
                    hi = mid
        return result
    except PreflightError:
        raise
    except (httpx.HTTPError, KeyError, TypeError, ValueError, ArithmeticError) as exc:
        raise PreflightError("目前無法確認報價與商品資料，請稍後查詢；沒有建立副本") from exc
