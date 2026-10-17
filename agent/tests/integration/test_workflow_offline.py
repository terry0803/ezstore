"""整張 Workflow 的離線整合測試：分類器換成假模型，不需要 API key。

MCP 工具也換成記憶體假的工具，不連服務、不讀寫真實資料庫。
"""

import json
import re
from collections.abc import AsyncGenerator

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
        elif "報價因子" in user_line:
            intent = {"intent": "update_pricing_factor", "new_pricing_factor": 1.5}
        elif "總價" in user_line:
            intent = {"intent": "adjust_total_price", "target_total_price": 8000}
        elif "複製" in user_line:
            intent = {"intent": "duplicate_quotation"}
        elif "轉" in user_line and "訂單" in user_line:
            intent = {"intent": "convert_to_order"}
        elif user_line.startswith("QT-"):
            intent = {"intent": "provide_info"}
        else:
            intent = {"intent": "get_quotation"}
        yield LlmResponse(
            content=types.Content(role="model", parts=[types.Part(text=json.dumps(intent))])
        )


class FakeTool:
    def __init__(self, name, calls):
        self.name, self.calls = name, calls

    async def run_async(self, *, args, tool_context):
        self.calls.append((self.name, args))
        if self.name == "list_customer_quotations":
            text = "QT-20260115-001 http://localhost:3000/quotations/1"
        elif self.name == "convert_to_order":
            text = "原始報價單未修改；訂單 ORD-20261017-001 http://localhost:3000/orders/11"
        elif self.name == "get_quotation":
            text = f"報價單 {args['quotation_number']} http://localhost:3000/quotations/12"
        else:
            text = "原始報價單未修改；新報價單 QT-20261017-001 http://localhost:3000/quotations/13"
        return {"content": [{"type": "text", "text": text}]}


class FakeToolset:
    def __init__(self):
        self.calls = []

    async def get_tools(self):
        return [FakeTool(name, self.calls) for name in agent_module.OPERATIONS]


@pytest.fixture
def runner(monkeypatch):
    # 走 Gemini 分支的憑證檢查，但模型已換成假的，不會真的呼叫 API
    monkeypatch.setattr(agent_module, "MODEL", "gemini-3.8-flash")
    monkeypatch.setenv("GEMINI_API_KEY", "offline-test")
    fake = FakeClassifier()
    # Workflow compiles/clones LlmAgents at construction; patch its actual nodes.
    for node in agent_module.root_agent.graph.nodes:
        if node.name == "classify_intent":
            monkeypatch.setattr(node, "model", fake)
    monkeypatch.setattr(agent_module.classify_intent, "model", fake)
    monkeypatch.setattr(agent_module, "mcp_toolset", FakeToolset())
    yield InMemoryRunner(app=agent_module.app)


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
async def test_list_customer_quotations_via_mcp(runner):
    session = await runner.session_service.create_session(
        app_name="quotation_agent", user_id="t"
    )
    reply = await _ask(runner, session.id, "我要查詢客戶的報價單清單，客戶名稱：史塔克工業")
    assert "QT-20260115-001" in reply


@pytest.mark.asyncio
@pytest.mark.parametrize(("text", "operation", "args"), [
    ("複製報價單 QT-20260330-001", "duplicate_quotation", {"quotation_number": "QT-20260330-001"}),
    ("報價單 QT-20260330-001 報價因子改為 1.5", "update_pricing_factor", {"quotation_number": "QT-20260330-001", "new_pricing_factor": 1.5}),
    ("報價單 QT-20260330-001 總價改為 8000", "adjust_total_price", {"quotation_number": "QT-20260330-001", "target_total_price": 8000.0}),
    ("報價單 QT-20260330-001 轉訂單", "convert_to_order", {"quotation_number": "QT-20260330-001"}),
])
async def test_mutating_routes_use_only_fake_mcp(runner, text, operation, args):
    session = await runner.session_service.create_session(app_name="quotation_agent", user_id="t")
    reply = await _ask(runner, session.id, text)
    assert agent_module.mcp_toolset.calls == [(operation, args)]
    assert "原始報價單未修改" in reply
    assert re.search(r"/(quotations|orders)/\d+", reply)


def test_fixture_replaces_compiled_model(runner):
    node = next(n for n in agent_module.root_agent.graph.nodes if n.name == "classify_intent")
    assert node is not agent_module.classify_intent
    assert isinstance(node.model, FakeClassifier)
