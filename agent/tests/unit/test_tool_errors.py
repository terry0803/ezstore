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


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "tool,message,hint",
    [
        ("adjust_total_price", "後端服務逾時，請稍後再試", True),
        ("convert_to_order", "無法連線後端服務：connection refused", True),
        ("update_pricing_factor", "後端回應 502：bad gateway", True),
        ("update_pricing_factor", "找不到報價單編號 QT-20990101-001", False),
        ("get_quotation", "後端服務逾時，請稍後再試", False),
    ],
)
async def test_partial_write_failure_asks_user_to_check(monkeypatch, tool, message, hint):
    """實測：改總價二分到一半後端斷掉時，複製單已經建好；回覆要提醒先查詢，不能只說失敗。"""
    async def run_async(**_kwargs):
        return {"isError": True, "content": [{"type": "text", "text": f"Error executing tool {tool}: {message}"}]}

    async def get_tools():
        return [SimpleNamespace(name=tool, run_async=run_async)]

    monkeypatch.setattr(agent, "mcp_toolset", SimpleNamespace(get_tools=get_tools))
    reply = await agent._call_mcp_tool(None, tool, {"quotation_number": "QT-20260330-001"})
    assert reply.startswith(f"操作失敗：{message}")
    assert ("請先查詢確認" in reply) is hint


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["discovery_error", "missing_tool"])
@pytest.mark.parametrize("name", sorted(agent._WRITE_TOOLS))
async def test_pre_dispatch_failure_is_explicitly_safe_to_retry(monkeypatch, failure, name):
    async def never_run(**kwargs):
        pytest.fail("No write may run before discovery succeeds")

    async def get_tools():
        if failure == "discovery_error":
            raise ConnectionError("MCP temporarily unavailable")
        return [SimpleNamespace(name="unrelated", run_async=never_run)]

    monkeypatch.setattr(agent, "mcp_toolset", SimpleNamespace(get_tools=get_tools))
    reply = await agent._call_mcp_tool(None, name, {})
    assert reply.startswith("未送出操作：")
    assert "目前連不到" in reply if failure == "discovery_error" else "沒有提供" in reply
