"""A2A 用戶端：agent card 的檢查（名稱、skill）與 JSON-RPC 位址固定送回取得 card 的地方。"""

import httpx
import pytest
from types import SimpleNamespace

import pricing_advisor.a2a_client as a2a
from pricing_advisor.a2a_client import A2AError, QuotationAgentClient

BASE = "http://localhost:3000/agent-api/a2a/quotation_agent"


def card(name="quotation_agent", skills=("get_quotation", "adjust_total_price", "convert_to_order"), url="http://agent:8080/a2a/quotation_agent"):
    return {
        "name": name,
        "description": "test",
        "version": "0.0.0",
        "supportedInterfaces": [{"url": url, "protocolBinding": "JSONRPC", "protocolVersion": "1.0"}],
        "capabilities": {},
        "defaultInputModes": ["text/plain"],
        "defaultOutputModes": ["text/plain"],
        "skills": [{"id": s, "name": s, "description": s, "tags": ["t"]} for s in skills],
    }


def client_with(card_json):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/.well-known/agent-card.json")
        return httpx.Response(200, json=card_json)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_card_rpc_url_is_pinned_to_where_the_card_came_from():
    # card 裡寫的是 compose 內部位址，甚至可能指到別的主機；一律改送回 BASE
    async with client_with(card(url="http://evil.example/steal")) as http:
        fetched = await QuotationAgentClient(BASE).fetch_card(http)
    assert [i.url for i in fetched.supported_interfaces] == [BASE]


@pytest.mark.asyncio
async def test_wrong_agent_is_rejected():
    async with client_with(card(name="someone_else")) as http:
        with pytest.raises(A2AError, match="不是 quotation_agent"):
            await QuotationAgentClient(BASE).fetch_card(http)


@pytest.mark.asyncio
async def test_missing_skill_is_rejected():
    async with client_with(card(skills=("get_quotation",))) as http:
        with pytest.raises(A2AError, match="adjust_total_price"):
            await QuotationAgentClient(BASE).fetch_card(http)


@pytest.mark.asyncio
@pytest.mark.parametrize("send_fails", [False, True])
async def test_cleanup_failure_does_not_replace_send_outcome(monkeypatch, send_fails):
    fake_card = SimpleNamespace(name="quotation_agent", skills=[])

    async def fetch(self, http):
        return fake_card

    class Peer:
        async def send_message(self, request):
            if send_fails:
                raise ValueError("send failed")
            yield SimpleNamespace(HasField=lambda field: field == "message",
                                  message=SimpleNamespace(context_id="context"))

        async def close(self):
            raise RuntimeError("cleanup failed")

    monkeypatch.setattr(QuotationAgentClient, "fetch_card", fetch)
    monkeypatch.setattr(a2a, "ClientFactory", lambda config: SimpleNamespace(create=lambda card: Peer()))
    monkeypatch.setattr(a2a, "get_message_text", lambda message: "completed reply")
    if send_fails:
        with pytest.raises(A2AError, match="ValueError") as error:
            await QuotationAgentClient(BASE).send("test")
        assert error.value.may_have_written is True
    else:
        result = await QuotationAgentClient(BASE).send("test")
        assert result.text == "completed reply"


@pytest.mark.asyncio
async def test_factory_failure_is_known_not_sent(monkeypatch):
    async def fetch(self, http):
        return SimpleNamespace(name="quotation_agent", skills=[])

    def broken(card):
        raise ValueError("unsupported transport")

    monkeypatch.setattr(QuotationAgentClient, "fetch_card", fetch)
    monkeypatch.setattr(a2a, "ClientFactory", lambda config: SimpleNamespace(create=broken))
    with pytest.raises(A2AError) as error:
        await QuotationAgentClient(BASE).send("test")
    assert error.value.may_have_written is False


def _task(state, text=None, task_id="task-1"):
    from a2a.helpers import new_text_artifact
    from a2a.types import Task, TaskState, TaskStatus

    task = Task(id=task_id, context_id="ctx", status=TaskStatus(state=getattr(TaskState, f"TASK_STATE_{state}")))
    if text:
        task.artifacts.append(new_text_artifact("reply", text))
    return task


def _peer(monkeypatch, polled=(), list_result=None, get_error=None):
    """假的 A2A 用戶端：送出時只回 task 編號（submitted），之後 get_task 依序回 polled 裡的狀態。"""
    from a2a.types import ListTasksResponse, StreamResponse

    seen = {"requests": [], "gets": 0}
    polled = list(polled)

    class Peer:
        async def send_message(self, request):
            seen["requests"].append(request)
            yield StreamResponse(task=_task("SUBMITTED"))

        async def get_task(self, request):
            seen["gets"] += 1
            if get_error is not None:
                raise get_error
            return polled.pop(0) if len(polled) > 1 else polled[0]

        async def list_tasks(self, request):
            seen["list_context"] = request.context_id
            return ListTasksResponse(tasks=list_result or [])

        async def close(self):
            pass

    async def fetch(self, http):
        return SimpleNamespace(name="quotation_agent", skills=[])

    monkeypatch.setattr(QuotationAgentClient, "fetch_card", fetch)
    monkeypatch.setattr(a2a, "ClientFactory", lambda config: SimpleNamespace(create=lambda card: Peer()))
    return seen


@pytest.mark.asyncio
async def test_send_returns_task_id_first_then_polls_until_done(monkeypatch):
    seen = _peer(monkeypatch, polled=[_task("WORKING"), _task("COMPLETED", "訂單編號: ORD-1")])
    dispatched = []
    client = QuotationAgentClient(BASE, poll_interval=0)
    result = await client.send("轉訂單", on_dispatch=lambda task_id, ctx: dispatched.append((task_id, ctx)))
    request = seen["requests"][0]
    assert request.configuration.return_immediately is True
    context_id = request.message.context_id
    # 送出前先記對話編號，拿到 task 編號後再記一次
    assert dispatched == [(None, context_id), ("task-1", context_id)]
    assert seen["gets"] == 2
    assert result.text == "訂單編號: ORD-1" and result.state == "completed" and result.task_id == "task-1"


@pytest.mark.asyncio
async def test_poll_timeout_keeps_the_task_id(monkeypatch):
    _peer(monkeypatch, polled=[_task("WORKING")])
    with pytest.raises(A2AError) as error:
        await QuotationAgentClient(BASE, timeout=0.05, poll_interval=0.01).send("轉訂單")
    assert error.value.may_have_written is True and error.value.stopped is False
    assert error.value.task_id == "task-1" and error.value.context_id


@pytest.mark.asyncio
@pytest.mark.parametrize("final", ["FAILED", "CANCELED"])
async def test_stopped_task_is_reported_as_stopped(monkeypatch, final):
    _peer(monkeypatch, polled=[_task(final)])
    with pytest.raises(A2AError) as error:
        await QuotationAgentClient(BASE, poll_interval=0).send("轉訂單")
    assert error.value.stopped is True and error.value.task_id == "task-1"


@pytest.mark.asyncio
async def test_task_vanishing_while_polling_is_reported_as_stopped(monkeypatch):
    from a2a.utils.errors import TaskNotFoundError

    _peer(monkeypatch, get_error=TaskNotFoundError())
    with pytest.raises(A2AError) as error:
        await QuotationAgentClient(BASE, poll_interval=0).send("轉訂單")
    assert error.value.stopped is True and "沒有這個 task" in str(error.value)


@pytest.mark.asyncio
async def test_task_state_by_id_and_by_context(monkeypatch):
    from a2a.utils.errors import TaskNotFoundError

    client = QuotationAgentClient(BASE)
    _peer(monkeypatch, polled=[_task("WORKING")])
    assert await client.task_state("task-1", "ctx") == "working"
    _peer(monkeypatch, get_error=TaskNotFoundError())
    assert await client.task_state("task-1", "ctx") == "not_found"
    _peer(monkeypatch, get_error=httpx.ConnectError("down"))
    with pytest.raises(A2AError, match="ConnectError"):
        await client.task_state("task-1", "ctx")
    # 沒有 task 編號時用對話編號查；有一個還在跑就算還在跑
    seen = _peer(monkeypatch, list_result=[_task("COMPLETED", task_id="a"), _task("WORKING", task_id="b")])
    assert await client.task_state(None, "ctx-9") == "working"
    assert seen["list_context"] == "ctx-9"
    _peer(monkeypatch, list_result=[])
    assert await client.task_state(None, "ctx-9") == "not_found"
