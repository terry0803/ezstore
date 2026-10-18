"""EZStore 後端 REST API 的唯讀用戶端：只用 GET，會改資料的事一律交給報價單 Agent。"""

from __future__ import annotations

import os
from decimal import Decimal
from typing import Any

import httpx


class BackendError(RuntimeError):
    """後端連不到、回錯誤或找不到資料。"""


class Backend:
    def __init__(self, base_url: str | None = None, timeout: float = 15.0, transport: httpx.AsyncBaseTransport | None = None):
        self.base_url = (base_url or os.getenv("BACKEND_API") or "http://localhost:8080/api/v1").rstrip("/")
        self._timeout = timeout
        self._transport = transport

    def url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    async def _get(self, path: str, **params: Any) -> Any:
        async with httpx.AsyncClient(base_url=self.base_url, timeout=self._timeout, transport=self._transport) as client:
            try:
                response = await client.get(path, params={k: v for k, v in params.items() if v is not None})
            except httpx.HTTPError as e:
                raise BackendError(f"連不到後端 {self.base_url}：{e.__class__.__name__}") from e
        if response.status_code == 404:
            raise BackendError("找不到資料")
        if response.status_code >= 400:
            raise BackendError(f"後端回應 {response.status_code}")
        return response.json()

    async def find_quotation(self, quotation_number: str) -> dict | None:
        """用報價單編號精確查詢，再取完整的報價單（含客戶與品項）。找不到回 None。"""
        data = await self._get("/quotations", quotation_number=quotation_number, page_size=1)
        first = (data.get("data") or [None])[0]
        if not first or first.get("quotation_number") != quotation_number:
            return None
        return await self._get(f"/quotations/{first['id']}")

    async def customer_orders(self, customer_id: int) -> list[dict]:
        """某個客戶的所有訂單。GET /orders 不能用報價單篩選，所以用客戶篩再自己比對。"""
        orders: list[dict] = []
        page = 1
        while True:
            data = await self._get("/orders", customer_id=customer_id, page=page, page_size=100)
            batch = data.get("data") or []
            orders.extend(batch)
            if not batch or page * 100 >= int(data.get("total") or 0):
                return orders
            page += 1

    async def require_current_catalog(self, quotation: dict) -> None:
        """Reject historical costs that the teacher's duplicate/update replaces."""
        current_level = (quotation.get('customer') or {}).get('level')
        if current_level and current_level != quotation.get('customer_level'):
            raise BackendError("客戶等級已不同於原報價快照；請先建立最新報價，這次沒有改資料")
        for item in quotation.get("items") or []:
            product = await self._get(f"/products/{item['product_id']}")
            if (Decimal(str(product['cost'])) != Decimal(str(item['product_cost']))
                    or Decimal(str(product['list_price'])) != Decimal(str(item['list_price']))):
                raise BackendError("目前商品成本或牌價已不同於原報價快照；請先以最新商品資料建立報價後再試算，這次沒有改資料")
