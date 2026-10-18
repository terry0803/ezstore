"""用 A2A 協定呼叫報價單 Agent（a2a-sdk 的 client）。

流程：抓 agent card → 確認名稱與需要的 skill → 送 message（對方先回 task 編號）→ 查 task 直到結束 → 取 artifact 的文字。

送出時先拿到 task 編號（return_immediately），之後就算這邊等到逾時，也能再問對方那個 task 結束了沒，
不必猜遠端還會不會寫入。對話編號（context_id）在送出前就由這邊產生，連 task 編號都沒拿到時用它查。

agent card 裡的 JSON-RPC 位址可能是 Compose 內部的 http://agent:8080/...，從本機經
前端 nginx（/agent-api/a2a/...）連的時候連不到，所以一律把 JSON-RPC 送回取得 card 的
同一個位址。ADK 的 RemoteA2aAgent 會拒絕非 https、非 loopback 的 card 位址
（_validate_card_rpc_targets），Docker 內部網路用不了，所以這裡直接用 a2a-sdk。
"""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field

import httpx
from a2a.client import A2ACardResolver, ClientConfig, ClientFactory
from a2a.helpers import get_artifact_text, get_message_text, new_text_message
from a2a.types import AgentCard, GetTaskRequest, ListTasksRequest, Role, SendMessageRequest, TaskState
from a2a.utils.errors import TaskNotFoundError

EXPECTED_AGENT = "quotation_agent"
REQUIRED_SKILLS = ("get_quotation", "adjust_total_price", "convert_to_order")
# 這些狀態代表對方已經不會再動資料：做完、失敗、取消、拒絕，或停下來等使用者輸入
STOPPED_STATES = frozenset({"completed", "failed", "canceled", "rejected", "input_required", "auth_required"})


class A2AError(RuntimeError):
    """抓不到 agent card、對方不是預期的 Agent、或 task 沒有完成。"""

    def __init__(self, message: str, *, may_have_written: bool = True, task_id: str | None = None,
                 context_id: str | None = None, stopped: bool = False):
        super().__init__(message)
        # A lost response does not prove that the remote mutation stopped.
        self.may_have_written = may_have_written
        self.task_id = task_id
        self.context_id = context_id
        # True：對方的 task 已經停下來（失敗、取消…），不會再寫入；之後重讀資料就知道有沒有改到
        self.stopped = stopped


@dataclass
class A2AResult:
    text: str
    task_id: str
    context_id: str
    state: str
    agent: str
    skills: list[str] = field(default_factory=list)

    def trace(self) -> dict:
        return {
            "agent": self.agent,
            "task_id": self.task_id,
            "context_id": self.context_id,
            "state": self.state,
        }


def _state_name(state: int) -> str:
    return TaskState.Name(state).removeprefix("TASK_STATE_").lower()


class QuotationAgentClient:
    def __init__(self, base_url: str | None = None, timeout: float = 240.0, poll_interval: float = 1.0):
        self.base_url = (
            base_url
            or os.getenv("QUOTATION_AGENT_URL")
            or "http://localhost:3000/agent-api/a2a/quotation_agent"
        ).rstrip("/")
        self.timeout = timeout
        self.poll_interval = poll_interval

    async def fetch_card(self, http: httpx.AsyncClient) -> AgentCard:
        try:
            card = await A2ACardResolver(http, self.base_url).get_agent_card()
        except Exception as e:
            raise A2AError(f"抓不到報價單 Agent 的 agent card（{self.base_url}）：{e.__class__.__name__}", may_have_written=False) from e
        if card.name != EXPECTED_AGENT:
            raise A2AError(f"agent card 的名稱是 {card.name}，不是 {EXPECTED_AGENT}", may_have_written=False)
        skills = {s.id for s in card.skills}
        missing = [s for s in REQUIRED_SKILLS if s not in skills]
        if missing:
            raise A2AError(f"報價單 Agent 沒有需要的 skill：{', '.join(missing)}", may_have_written=False)
        for interface in card.supported_interfaces:
            interface.url = self.base_url
        return card

    def _client(self, http: httpx.AsyncClient, card: AgentCard):
        try:
            return ClientFactory(ClientConfig(streaming=False, httpx_client=http)).create(card)
        except Exception as e:
            raise A2AError(f"無法準備 A2A 用戶端：{e.__class__.__name__}", may_have_written=False) from e

    @staticmethod
    async def _close(client) -> None:
        try:
            await client.close()
        except Exception as e:
            # Preserve a completed result or the original send failure.
            # Cleanup failure is not a reason to send the mutation again.
            logging.getLogger(__name__).warning("A2A client cleanup failed: %s", type(e).__name__)

    async def send(self, text: str, on_dispatch: Callable[[str | None, str], None] | None = None) -> A2AResult:
        """送出並等 task 結束。on_dispatch(task_id, context_id) 在送出前和拿到 task 編號後各呼叫一次，
        呼叫端可以先記下來：就算之後這個 coroutine 被取消或逾時，也查得到那次送出的結果。"""
        context_id = uuid.uuid4().hex
        loop = asyncio.get_running_loop()
        async with httpx.AsyncClient(timeout=self.timeout) as http:
            card = await self.fetch_card(http)
            client = self._client(http, card)
            message = new_text_message(text, role=Role.ROLE_USER, context_id=context_id)
            request = SendMessageRequest(message=message)
            request.configuration.return_immediately = True
            task = None
            reply = None
            try:
                if on_dispatch:
                    on_dispatch(None, context_id)
                try:
                    async for response in client.send_message(request):
                        if response.HasField("task"):
                            task = response.task
                        elif response.HasField("message"):
                            reply = response.message
                except Exception as e:
                    raise A2AError(f"A2A 呼叫失敗：{e.__class__.__name__}", context_id=context_id) from e
                if task is not None:
                    if on_dispatch:
                        on_dispatch(task.id, context_id)
                    deadline = loop.time() + self.timeout
                    while _state_name(task.status.state) not in STOPPED_STATES:
                        if loop.time() > deadline:
                            raise A2AError("等報價單 Agent 完成逾時", task_id=task.id, context_id=context_id)
                        await asyncio.sleep(self.poll_interval)
                        try:
                            task = await client.get_task(GetTaskRequest(id=task.id))
                        except TaskNotFoundError as e:
                            # 對方已經沒有這個 task：報價單 Agent 重啟過，正在做的工作也跟著停了
                            raise A2AError("報價單 Agent 已經沒有這個 task（可能重啟過）", task_id=task.id,
                                           context_id=context_id, stopped=True) from e
                        except Exception:
                            continue  # 暫時查不到就再等，逾時前一直試
            finally:
                await self._close(client)

        skills = [s.id for s in card.skills]
        if task is not None:
            state = _state_name(task.status.state)
            texts = [get_artifact_text(a) for a in task.artifacts]
            if not any(texts) and task.status.HasField("message"):
                texts = [get_message_text(task.status.message)]
            if state != "completed":
                raise A2AError(f"報價單 Agent 的 task 狀態是 {state}", task_id=task.id, context_id=context_id, stopped=True)
            return A2AResult("\n".join(t for t in texts if t), task.id, task.context_id, state, card.name, skills)
        if reply is not None:
            return A2AResult(get_message_text(reply), "", reply.context_id, "message", card.name, skills)
        raise A2AError("報價單 Agent 沒有回應", context_id=context_id)

    async def task_state(self, task_id: str | None, context_id: str | None) -> str:
        """查之前送出的 task 現在的狀態。回傳狀態名稱，或 "not_found"（對方沒有這個 task：沒收到，
        或報價單 Agent 重啟過，記憶體裡的 task 和正在做的工作都已經不在）。連不到時丟 A2AError。"""
        async with httpx.AsyncClient(timeout=30.0) as http:
            card = await self.fetch_card(http)
            client = self._client(http, card)
            try:
                if task_id:
                    try:
                        task = await client.get_task(GetTaskRequest(id=task_id))
                    except TaskNotFoundError:
                        return "not_found"
                    except Exception as e:
                        raise A2AError(f"查不到 task 狀態：{e.__class__.__name__}") from e
                    return _state_name(task.status.state)
                if context_id:
                    try:
                        listed = await client.list_tasks(ListTasksRequest(context_id=context_id))
                    except Exception as e:
                        raise A2AError(f"查不到 task 清單：{e.__class__.__name__}") from e
                    if not listed.tasks:
                        return "not_found"
                    states = [_state_name(t.status.state) for t in listed.tasks]
                    return next((st for st in states if st not in STOPPED_STATES), states[-1])
                raise A2AError("沒有 task 編號也沒有對話編號，無法查詢")
            finally:
                await self._close(client)
