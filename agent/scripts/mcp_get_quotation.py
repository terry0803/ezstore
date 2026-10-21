"""spec 4.1：用 MCP client 直接呼叫 MCP Server 的 get_quotation，印出回傳的文字。

    uv run python scripts/mcp_get_quotation.py [報價單編號] [--url http://localhost:8010/mcp]

不經過 Agent 和模型。先列出 Server 提供的工具，再查報價單（預設 QT-20260330-001），
回傳的文字應該有品項和系統連結。
"""

import argparse
import asyncio

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


async def main(url: str, quotation_number: str) -> None:
    async with streamable_http_client(url) as streams, ClientSession(streams[0], streams[1]) as session:
        await session.initialize()
        tools = await session.list_tools()
        print("MCP 工具：" + "、".join(t.name for t in tools.tools))
        print(f"\n呼叫 get_quotation(quotation_number=\"{quotation_number}\")\n")
        result = await session.call_tool("get_quotation", {"quotation_number": quotation_number})
        for block in result.content:
            print(getattr(block, "text", block))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("quotation_number", nargs="?", default="QT-20260330-001")
    ap.add_argument("--url", default="http://localhost:8010/mcp")
    args = ap.parse_args()
    asyncio.run(main(args.url, args.quotation_number))
