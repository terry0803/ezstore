"""No real peer: delayed commits model timeouts/cancellation after dispatch."""
import asyncio
import copy
from types import SimpleNamespace

import pytest

from pricing_advisor import agent
from pricing_advisor.a2a_client import A2AError, A2AResult
from tests.conftest import FakeBackend, SNAPSHOT

NUMBER = "QT-20260301-001"


@pytest.fixture
def conversion(monkeypatch):
    backend = FakeBackend(quotations=copy.deepcopy(SNAPSHOT["quotations"]),
                          orders=copy.deepcopy(SNAPSHOT["orders_by_customer"]))
    monkeypatch.setattr(agent, "backend", backend)
    monkeypatch.setattr(agent, "_CONVERT_LOCKS", {})
    if hasattr(agent, "_CONVERT_UNCERTAIN"):
        monkeypatch.setattr(agent, "_CONVERT_UNCERTAIN", set())
    quote = backend.quotations[NUMBER]

    def commit(number=999):
        order = {"id": number, "order_number": f"ORD-20261017-{number:03}",
                 "quotation_id": quote["id"], "customer_id": quote["customer_id"],
                 "status": "pending", "items": copy.deepcopy(quote["items"]),
                 "total_price": quote["total_price"]}
        backend.orders.setdefault(str(quote["customer_id"]), []).append(order)
        return order

    async def request():
        event = await agent.order_check(SimpleNamespace(state={}), {"quotation_number": NUMBER, "convert": True})
        assert event.actions.route == "delegate"
        return copy.deepcopy(event.output)

    return backend, quote, commit, request


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["timeout", "cancel", "unverified_completed_reply"])
async def test_uncertain_dispatch_does_not_send_a_second_conversion(conversion, monkeypatch, failure):
    backend, quote, commit, request = conversion
    inputs = [await request(), await request()]
    release, dispatched = asyncio.Event(), asyncio.Event()
    remote_tasks, calls = [], []

    async def later_commit(number):
        await release.wait()
        commit(number)

    async def send(text):
        calls.append(text)
        remote_tasks.append(asyncio.create_task(later_commit(998 + len(calls))))
        dispatched.set()
        if failure == "cancel":
            await asyncio.Event().wait()
        if failure == "unverified_completed_reply":
            return A2AResult("操作中斷，尚無法確認是否完成", "task", "context", "completed", "quotation_agent")
        raise A2AError("timed out after request dispatch")

    monkeypatch.setattr(agent, "quotation_agent", SimpleNamespace(send=send))
    first = asyncio.create_task(agent.delegate_a2a(None, inputs[0]))
    try:
        await dispatched.wait()
        if failure == "cancel":
            first.cancel()
            with pytest.raises(asyncio.CancelledError):
                await first
        else:
            await first
        # Remote work has not committed yet, so rereading orders alone sees none.
        second = await asyncio.wait_for(agent.delegate_a2a(None, inputs[1]), 1)
        assert len(calls) == 1
        assert "尚未確認" in second.output and "沒有再次送出" in second.output
    finally:
        release.set()
        if not first.done():
            first.cancel()
        await asyncio.gather(first, *remote_tasks, return_exceptions=True)
    linked = [row for row in backend.orders[str(quote["customer_id"])] if row["quotation_id"] == quote["id"]]
    assert len(linked) == 1
    # 遠端稍後完成時，重讀會找到訂單並解除未明標記，但仍拒絕重複轉單。
    third = await agent.delegate_a2a(None, inputs[1])
    assert "已經有訂單" in third.output and "這次沒有轉訂單" in third.output
    assert len(calls) == 1
    assert NUMBER not in agent._CONVERT_UNCERTAIN


@pytest.mark.asyncio
async def test_known_preflight_failure_allows_safe_retry(conversion, monkeypatch):
    _, _, commit, request = conversion
    inputs = [await request(), await request()]
    calls = []

    async def send(text):
        calls.append(text)
        if len(calls) == 1:
            raise A2AError("agent card unavailable", may_have_written=False)
        order = commit()
        return A2AResult(f"訂單編號: {order['order_number']}", "task", "context", "completed", "quotation_agent")

    monkeypatch.setattr(agent, "quotation_agent", SimpleNamespace(send=send))
    await agent.delegate_a2a(None, inputs[0])
    result = await agent.delegate_a2a(None, inputs[1])
    assert len(calls) == 2
    assert "改完後核對：後端查得到" in result.output
    assert NUMBER not in agent._CONVERT_UNCERTAIN


@pytest.mark.asyncio
async def test_rule_reload_failure_does_not_escape_or_send(conversion, monkeypatch):
    _, _, _, request = conversion
    body = await request()
    calls = []

    def broken():
        raise agent.OKFError("knowledge file unavailable")

    async def send(text):
        calls.append(text)

    monkeypatch.setattr(agent, "_bundle", broken)
    monkeypatch.setattr(agent, "quotation_agent", SimpleNamespace(send=send))
    result = await agent.delegate_a2a(None, body)
    assert "這次沒有轉訂單" in result.output
    assert calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("reply,still_blocked", [
    ("操作失敗：後端回應 400：關聯報價單與訂單必須屬於同一客戶", False),
    ("操作失敗：找不到資料", False),
    ("操作失敗：後端服務逾時，請稍後再試\n這次操作可能已經建立了新的報價單或訂單，請先查詢確認，再決定要不要重試，免得重複建立。", True),
    ("操作中斷，尚無法確認是否已完成。請先查詢報價單或訂單確認結果，再決定是否重試，避免重複建立資料。", True),
])
async def test_completed_definite_failure_releases_guard(conversion, monkeypatch, reply, still_blocked):
    """對方已完成且明確回報沒寫入的失敗，不必等重啟；中斷或逾時才繼續擋。"""
    _, _, _, request = conversion
    calls = []

    async def send(text):
        calls.append(text)
        return A2AResult(reply, "task", "context", "completed", "quotation_agent")

    monkeypatch.setattr(agent, "quotation_agent", SimpleNamespace(send=send))
    await agent.delegate_a2a(None, await request())
    assert (NUMBER in agent._CONVERT_UNCERTAIN) is still_blocked
    second = await agent.delegate_a2a(None, await request())
    assert len(calls) == (1 if still_blocked else 2)
    if still_blocked:
        assert "沒有再次送出" in second.output
