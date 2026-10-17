from types import SimpleNamespace

import pytest

from quotation_agent import agent


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["get_quotation", "update_pricing_factor"])
async def test_tool_execution_timeout_becomes_final_text(monkeypatch, name):
    calls = []

    async def run_async(**kwargs):
        calls.append(kwargs)
        raise TimeoutError("transport failure")

    async def get_tools():
        return [SimpleNamespace(name=name, run_async=run_async)]

    monkeypatch.setattr(agent, "mcp_toolset", SimpleNamespace(get_tools=get_tools))
    reply = await agent._call_mcp_tool(None, name, {"quotation_number": "QT-20260330-001"})
    assert len(calls) == 1
    if name == "get_quotation":
        assert "操作失敗" in reply
    else:
        assert "先查詢" in reply and "避免重複" in reply


@pytest.mark.asyncio
async def test_network_guard_blocks_unmocked_http():
    import httpx

    with pytest.raises(AssertionError, match="Offline test"):
        async with httpx.AsyncClient() as client:
            await client.get("https://example.invalid")


@pytest.mark.asyncio
async def test_mcp_error_prefix_is_removed(monkeypatch):
    async def run_async(**_kwargs):
        return {"isError": True, "content": [{"type": "text", "text": "Error executing tool get_quotation: 找不到報價單編號 QT-20990101-001"}]}

    async def get_tools():
        return [SimpleNamespace(name="get_quotation", run_async=run_async)]

    monkeypatch.setattr(agent, "mcp_toolset", SimpleNamespace(get_tools=get_tools))
    reply = await agent._call_mcp_tool(None, "get_quotation", {"quotation_number": "QT-20990101-001"})
    assert reply == "操作失敗：找不到報價單編號 QT-20990101-001"
