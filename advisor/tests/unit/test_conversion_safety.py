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
    monkeypatch.setattr(agent, "_CONVERT_UNCERTAIN", {})
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


class Peer:
    """假的報價單 Agent：send 照真的 client 一樣先回報對話編號和 task 編號，task_state 回目前狀態。"""

    def __init__(self, reply):
        self.reply = reply
        self.calls = []
        self.state = "working"
        self.state_queries = []

    async def send(self, text, on_dispatch=None):
        self.calls.append(text)
        if on_dispatch:
            on_dispatch(None, f"ctx-{len(self.calls)}")
            on_dispatch(f"task-{len(self.calls)}", f"ctx-{len(self.calls)}")
        return await self.reply(len(self.calls))

    async def task_state(self, task_id, context_id):
        self.state_queries.append((task_id, context_id))
        if isinstance(self.state, Exception):
            raise self.state
        return self.state


def use_clock(monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(agent.time, "monotonic", lambda: clock[0])
    return clock


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["timeout", "cancel", "unverified_completed_reply"])
async def test_uncertain_dispatch_does_not_send_a_second_conversion(conversion, monkeypatch, failure):
    backend, quote, commit, request = conversion
    inputs = [await request(), await request()]
    release, dispatched = asyncio.Event(), asyncio.Event()
    remote_tasks = []

    async def later_commit(number):
        await release.wait()
        commit(number)

    async def reply(n):
        remote_tasks.append(asyncio.create_task(later_commit(998 + n)))
        dispatched.set()
        if failure == "cancel":
            await asyncio.Event().wait()
        if failure == "unverified_completed_reply":
            return A2AResult("操作中斷，尚無法確認是否完成", "task", "context", "completed", "quotation_agent")
        raise A2AError("timed out after request dispatch", task_id=f"task-{n}", context_id=f"ctx-{n}")

    peer = Peer(reply)
    monkeypatch.setattr(agent, "quotation_agent", peer)
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
        assert len(peer.calls) == 1
        assert "沒有再次送出" in second.output
        if failure != "unverified_completed_reply":
            assert peer.state_queries == [("task-1", "ctx-1")]
            assert "還在處理" in second.output
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
    assert len(peer.calls) == 1
    assert NUMBER not in agent._CONVERT_UNCERTAIN


@pytest.mark.asyncio
async def test_known_preflight_failure_allows_safe_retry(conversion, monkeypatch):
    _, _, commit, request = conversion
    inputs = [await request(), await request()]

    async def reply(n):
        if n == 1:
            raise A2AError("agent card unavailable", may_have_written=False)
        order = commit()
        return A2AResult(f"訂單編號: {order['order_number']}", "task", "context", "completed", "quotation_agent")

    peer = Peer(reply)
    monkeypatch.setattr(agent, "quotation_agent", peer)
    await agent.delegate_a2a(None, inputs[0])
    result = await agent.delegate_a2a(None, inputs[1])
    assert len(peer.calls) == 2
    assert "改完後核對：後端查得到" in result.output
    assert NUMBER not in agent._CONVERT_UNCERTAIN


@pytest.mark.asyncio
async def test_rule_reload_failure_does_not_escape_or_send(conversion, monkeypatch):
    _, _, _, request = conversion
    body = await request()

    def broken():
        raise agent.OKFError("knowledge file unavailable")

    async def reply(n):
        raise AssertionError("should not send")

    peer = Peer(reply)
    monkeypatch.setattr(agent, "_bundle", broken)
    monkeypatch.setattr(agent, "quotation_agent", peer)
    result = await agent.delegate_a2a(None, body)
    assert "這次沒有轉訂單" in result.output
    assert peer.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("text,still_blocked", [
    ("操作失敗：後端回應 400：關聯報價單與訂單必須屬於同一客戶", True),
    # convert_to_order 的 404 只會出在建訂單之前的讀取（POST /orders 只回 201 或 400），確定沒寫入
    ("操作失敗：找不到資料", False),
    ("未送出操作：找不到報價單編號 QT-20990101-001", False),
    ("操作失敗：後端服務逾時，請稍後再試\n這次操作可能已經建立了新的報價單或訂單，請先查詢確認，再決定要不要重試，免得重複建立。", True),
    ("操作中斷，尚無法確認是否已完成。請先查詢報價單或訂單確認結果，再決定是否重試，避免重複建立資料。", True),
])
async def test_completed_definite_failure_releases_guard(conversion, monkeypatch, text, still_blocked):
    """Preflight rejections and pre-write lookups release the guard; generic failures do not."""
    _, _, _, request = conversion

    async def reply(n):
        return A2AResult(text, "task", "context", "completed", "quotation_agent")

    peer = Peer(reply)
    monkeypatch.setattr(agent, "quotation_agent", peer)
    await agent.delegate_a2a(None, await request())
    assert (NUMBER in agent._CONVERT_UNCERTAIN) is still_blocked
    second = await agent.delegate_a2a(None, await request())
    assert len(peer.calls) == (1 if still_blocked else 2)
    if still_blocked:
        assert "沒有再次送出" in second.output and "結果仍未確認" in second.output


@pytest.mark.asyncio
@pytest.mark.parametrize("final_state", ["completed", "failed", "canceled", "not_found"])
async def test_stopped_or_missing_task_never_proves_database_rollback(conversion, monkeypatch, final_state):
    """No elapsed time permits a second write without evidence of the first result."""
    _, _, commit, request = conversion
    clock = use_clock(monkeypatch)

    async def reply(n):
        if n == 1:
            raise A2AError("timed out after request dispatch", task_id="task-1", context_id="ctx-1")
        order = commit()
        return A2AResult(f"訂單編號: {order['order_number']}", "task", "context", "completed", "quotation_agent")

    peer = Peer(reply)
    monkeypatch.setattr(agent, "quotation_agent", peer)
    first = await agent.delegate_a2a(None, await request())
    assert "可能已送出操作" in first.output
    assert agent._CONVERT_UNCERTAIN[NUMBER]["task_id"] == "task-1"

    clock[0] += 3600  # 時間過多久都一樣：task 還在跑就不送
    working = await agent.delegate_a2a(None, await request())
    assert len(peer.calls) == 1 and "還在處理" in working.output

    peer.state = final_state
    stopped = await agent.delegate_a2a(None, await request())
    assert len(peer.calls) == 1 and "沒有再次送出" in stopped.output

    clock[0] += 60
    early = await agent.delegate_a2a(None, await request())
    assert len(peer.calls) == 1 and "沒有再次送出" in early.output

    clock[0] += 61
    late = await agent.delegate_a2a(None, await request())
    assert len(peer.calls) == 1 and "沒有再次送出" in late.output
    assert NUMBER in agent._CONVERT_UNCERTAIN
    body = await request()
    commit()  # delayed original request finally commits; it is reconciled, never repeated
    reconciled = await agent.delegate_a2a(None, body)
    assert len(peer.calls) == 1 and "已經有訂單" in reconciled.output
    assert NUMBER not in agent._CONVERT_UNCERTAIN


@pytest.mark.asyncio
async def test_unreachable_peer_keeps_blocking(conversion, monkeypatch):
    """查不到 task 狀態就不能當作已經結束。"""
    _, _, _, request = conversion
    clock = use_clock(monkeypatch)

    async def reply(n):
        raise A2AError("timed out after request dispatch", task_id="task-1", context_id="ctx-1")

    peer = Peer(reply)
    peer.state = A2AError("connection refused")
    monkeypatch.setattr(agent, "quotation_agent", peer)
    await agent.delegate_a2a(None, await request())
    clock[0] += 3600
    second = await agent.delegate_a2a(None, await request())
    assert len(peer.calls) == 1
    assert "還沒辦法確認" in second.output and "沒有再次送出" in second.output
    assert NUMBER in agent._CONVERT_UNCERTAIN


@pytest.mark.asyncio
async def test_stopped_remote_task_does_not_expire_uncertainty(conversion, monkeypatch):
    """A stopped A2A task does not cancel its last backend request."""
    _, _, commit, request = conversion
    clock = use_clock(monkeypatch)

    async def reply(n):
        if n == 1:
            raise A2AError("報價單 Agent 的 task 狀態是 failed", task_id="task-1", context_id="ctx-1", stopped=True)
        order = commit()
        return A2AResult(f"訂單編號: {order['order_number']}", "task", "context", "completed", "quotation_agent")

    peer = Peer(reply)
    monkeypatch.setattr(agent, "quotation_agent", peer)
    await agent.delegate_a2a(None, await request())
    early = await agent.delegate_a2a(None, await request())
    assert len(peer.calls) == 1 and "沒有再次送出" in early.output
    assert peer.state_queries == []
    clock[0] += 121
    late = await agent.delegate_a2a(None, await request())
    assert len(peer.calls) == 1 and "沒有再次送出" in late.output


@pytest.mark.asyncio
async def test_cancel_before_dispatch_does_not_block(conversion, monkeypatch):
    """還沒送出就被取消（連對話編號都沒記下），表示對方沒有收到，下一次可以直接轉。"""
    _, _, commit, request = conversion
    started = asyncio.Event()
    calls = []

    async def send(text, on_dispatch=None):
        calls.append(text)
        if len(calls) == 1:
            started.set()
            await asyncio.Event().wait()  # 卡在抓 agent card，還沒呼叫 on_dispatch
        on_dispatch(None, "ctx-2")
        order = commit()
        return A2AResult(f"訂單編號: {order['order_number']}", "task", "context", "completed", "quotation_agent")

    monkeypatch.setattr(agent, "quotation_agent", SimpleNamespace(send=send))
    inputs = [await request(), await request()]
    first = asyncio.create_task(agent.delegate_a2a(None, inputs[0]))
    await started.wait()
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    second = await agent.delegate_a2a(None, inputs[1])
    assert len(calls) == 2 and "改完後核對：後端查得到" in second.output


@pytest.mark.asyncio
async def test_late_remote_commit_is_found_after_the_task_ends(conversion, monkeypatch):
    """等待期間遠端其實完成了：task 結束、等過 MCP 的逾時也不會再送，重讀看到訂單就擋下。"""
    _, _, commit, request = conversion
    clock = use_clock(monkeypatch)

    async def reply(n):
        raise A2AError("timed out after request dispatch", task_id="task-1", context_id="ctx-1")

    peer = Peer(reply)
    monkeypatch.setattr(agent, "quotation_agent", peer)
    await agent.delegate_a2a(None, await request())
    body = await request()  # 先通過 order_check，再讓遠端晚一步完成
    commit()
    peer.state = "completed"
    clock[0] += 3600
    result = await agent.delegate_a2a(None, body)
    assert len(peer.calls) == 1
    assert "已經有訂單" in result.output and "這次沒有轉訂單" in result.output
    assert NUMBER not in agent._CONVERT_UNCERTAIN
