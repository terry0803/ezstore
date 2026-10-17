"""用 A2A 協定呼叫報價單 Agent（a2a-sdk 的 client）。

流程：抓 agent card → 確認名稱與需要的 skill → 送 message → 等 task 完成 → 取 artifact 的文字。

agent card 裡的 JSON-RPC 位址可能是 Compose 內部的 http://agent:8080/...，從本機經
前端 nginx（/agent-api/a2a/...）連的時候連不到，所以一律把 JSON-RPC 送回取得 card 的
同一個位址。ADK 的 RemoteA2aAgent 會拒絕非 https、非 loopback 的 card 位址
（_validate_card_rpc_targets），Docker 內部網路用不了，所以這裡直接用 a2a-sdk。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

import httpx
from a2a.client import A2ACardResolver, ClientConfig, ClientFactory
from a2a.helpers import get_artifact_text, get_message_text, new_text_message
from a2a.types import AgentCard, Role, SendMessageRequest, TaskState

EXPECTED_AGENT = "quotation_agent"
REQUIRED_SKILLS = ("get_quotation", "adjust_total_price", "convert_to_order")


class A2AError(RuntimeError):
    """抓不到 agent card、對方不是預期的 Agent、或 task 沒有完成。"""


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
    def __init__(self, base_url: str | None = None, timeout: float = 240.0):
        self.base_url = (
            base_url
            or os.getenv("QUOTATION_AGENT_URL")
            or "http://localhost:3000/agent-api/a2a/quotation_agent"
        ).rstrip("/")
        self.timeout = timeout

    async def fetch_card(self, http: httpx.AsyncClient) -> AgentCard:
        try:
            card = await A2ACardResolver(http, self.base_url).get_agent_card()
        except Exception as e:
            raise A2AError(f"抓不到報價單 Agent 的 agent card（{self.base_url}）：{e.__class__.__name__}") from e
        if card.name != EXPECTED_AGENT:
            raise A2AError(f"agent card 的名稱是 {card.name}，不是 {EXPECTED_AGENT}")
        skills = {s.id for s in card.skills}
        missing = [s for s in REQUIRED_SKILLS if s not in skills]
        if missing:
            raise A2AError(f"報價單 Agent 沒有需要的 skill：{', '.join(missing)}")
        for interface in card.supported_interfaces:
            interface.url = self.base_url
        return card

    async def send(self, text: str) -> A2AResult:
        async with httpx.AsyncClient(timeout=self.timeout) as http:
            card = await self.fetch_card(http)
            client = ClientFactory(ClientConfig(streaming=False, httpx_client=http)).create(card)
            message = new_text_message(text, role=Role.ROLE_USER)
            task = None
            reply = None
            try:
                async for response in client.send_message(SendMessageRequest(message=message)):
                    if response.HasField("task"):
                        task = response.task
                    elif response.HasField("message"):
                        reply = response.message
            except Exception as e:
                raise A2AError(f"A2A 呼叫失敗：{e.__class__.__name__}") from e
            finally:
                await client.close()

        skills = [s.id for s in card.skills]
        if task is not None:
            state = _state_name(task.status.state)
            texts = [get_artifact_text(a) for a in task.artifacts]
            if not any(texts) and task.status.HasField("message"):
                texts = [get_message_text(task.status.message)]
            if state != "completed":
                raise A2AError(f"報價單 Agent 的 task 狀態是 {state}")
            return A2AResult("\n".join(t for t in texts if t), task.id, task.context_id, state, card.name, skills)
        if reply is not None:
            return A2AResult(get_message_text(reply), "", reply.context_id, "message", card.name, skills)
        raise A2AError("報價單 Agent 沒有回應")
