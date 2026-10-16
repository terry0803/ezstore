"""整張 Workflow 的離線整合測試：分類器換成假模型，不需要 API key。

需要 MCP Server 在 MCP_URL（預設 http://localhost:8010/mcp）可連線，連不到就略過。
只呼叫唯讀工具，不會改資料。
"""

import json
import os
import socket
from collections.abc import AsyncGenerator
from urllib.parse import urlparse

import pytest
from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_response import LlmResponse
from google.adk.runners import InMemoryRunner
from google.genai import types

import quotation_agent.agent as agent_module


class FakeClassifier(BaseLlm):
    """依使用者這一句回傳固定的 Intent JSON。"""

    model: str = "fake-classifier"

    async def generate_content_async(
        self, llm_request, stream: bool = False
    ) -> AsyncGenerator[LlmResponse, None]:
        text = "".join(
            p.text or "" for c in llm_request.contents for p in (c.parts or [])
        )
        user_line = text.split("使用者這一句：")[-1]
        if "天氣" in user_line:
            intent = {"intent": "off_topic"}
        elif "客戶" in user_line and "清單" in user_line:
            intent = {"intent": "list_customer_quotations", "customer_name": "史塔克工業"}
        elif user_line.startswith("QT-"):
            intent = {"intent": "provide_info"}
        else:
            intent = {"intent": "get_quotation"}
        yield LlmResponse(
            content=types.Content(role="model", parts=[types.Part(text=json.dumps(intent))])
        )


def _mcp_reachable() -> bool:
    url = urlparse(os.getenv("MCP_URL", "http://localhost:8010/mcp"))
    try:
        with socket.create_connection((url.hostname, url.port or 80), timeout=2):
            return True
    except OSError:
        return False


@pytest.fixture
def runner(monkeypatch):
    # 走 Gemini 分支的憑證檢查，但模型已換成假的，不會真的呼叫 API
    monkeypatch.setattr(agent_module, "MODEL", "gemini-3.8-flash")
    monkeypatch.setenv("GEMINI_API_KEY", "offline-test")
    original = agent_module.classify_intent.model
    agent_module.classify_intent.model = FakeClassifier()
    yield InMemoryRunner(app=agent_module.app)
    agent_module.classify_intent.model = original


async def _ask(runner, session_id, text):
    replies = []
    async for ev in runner.run_async(
        user_id="t",
        session_id=session_id,
        new_message=types.Content(role="user", parts=[types.Part.from_text(text=text)]),
    ):
        node = ev.node_info.path.split("/")[-1]
        if node.startswith("respond@") and ev.content and ev.content.parts:
            replies.append("".join(p.text or "" for p in ev.content.parts))
    return replies[-1] if replies else ""


@pytest.mark.asyncio
async def test_off_topic_is_refused_without_tools(runner):
    session = await runner.session_service.create_session(
        app_name="quotation_agent", user_id="t"
    )
    reply = await _ask(runner, session.id, "今天台北天氣如何？")
    assert "只能協助" in reply


@pytest.mark.asyncio
@pytest.mark.skipif(not _mcp_reachable(), reason="MCP Server 不在 MCP_URL")
async def test_clarify_then_complete_via_mcp(runner):
    session = await runner.session_service.create_session(
        app_name="quotation_agent", user_id="t"
    )
    first = await _ask(runner, session.id, "我要查詢報價單")
    assert first.startswith("請提供")
    second = await _ask(runner, session.id, "QT-20260330-001")
    assert "QT-20260330-001" in second
    assert "/quotations/" in second


@pytest.mark.asyncio
@pytest.mark.skipif(not _mcp_reachable(), reason="MCP Server 不在 MCP_URL")
async def test_list_customer_quotations_via_mcp(runner):
    session = await runner.session_service.create_session(
        app_name="quotation_agent", user_id="t"
    )
    reply = await _ask(runner, session.id, "我要查詢客戶的報價單清單，客戶名稱：史塔克工業")
    assert "QT-20260115-001" in reply
