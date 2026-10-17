"""A2A 示範：外部 client 用 A2A 協定呼叫兩個 Agent。

1. 讀兩張 agent card（報價單 Agent、議價顧問 Agent），列出 skill
2. 直接用 A2A 請報價單 Agent 查報價單
3. 用 A2A 請議價顧問改價：議價顧問再用 A2A 請報價單 Agent 去改（A2A 串接）

    cd advisor
    uv run python scripts/a2a_demo.py

需要 docker compose 啟動整套系統加上 docker-compose.advisor.yml。第 3 步會改資料，示範前先重灌 seed。
"""

import asyncio
import os
import sys
import time

import httpx
from a2a.client import A2ACardResolver, ClientConfig, ClientFactory
from a2a.helpers import get_artifact_text, new_text_message
from a2a.types import Role, SendMessageRequest, TaskState

QUOTATION_AGENT = os.getenv("QUOTATION_AGENT_URL", "http://localhost:3000/agent-api/a2a/quotation_agent")
ADVISOR = os.getenv("ADVISOR_URL", "http://localhost:8502/a2a/pricing_advisor")


async def card_of(http, base_url):
    card = await A2ACardResolver(http, base_url).get_agent_card()
    # 經 nginx 連的時候，card 裡寫的是 compose 內部位址，JSON-RPC 改送回取得 card 的位址
    for interface in card.supported_interfaces:
        interface.url = base_url
    return card


async def send(http, card, text):
    client = ClientFactory(ClientConfig(streaming=False, httpx_client=http)).create(card)
    start = time.perf_counter()
    task = None
    async for response in client.send_message(SendMessageRequest(message=new_text_message(text, role=Role.ROLE_USER))):
        if response.HasField("task"):
            task = response.task
    seconds = time.perf_counter() - start
    state = TaskState.Name(task.status.state).removeprefix("TASK_STATE_").lower()
    reply = "\n".join(get_artifact_text(a) for a in task.artifacts)
    print(f"  task {task.id[:8]}（context {task.context_id[:8]}），狀態 {state}，{seconds:.1f} 秒")
    print("  " + reply.replace("\n", "\n  "))


async def main():
    async with httpx.AsyncClient(timeout=300) as http:
        print("== 1. agent card")
        cards = {}
        for base in (QUOTATION_AGENT, ADVISOR):
            card = await card_of(http, base)
            cards[card.name] = card
            print(f"- {card.name}：{card.description}")
            for skill in card.skills:
                print(f"    skill {skill.id}：{skill.name}（例句：{skill.examples[0] if skill.examples else '無'}）")

        print("\n== 2. 直接用 A2A 呼叫報價單 Agent")
        text = "我要查詢報價單，報價單編號：QT-20260330-001"
        print(f"> {text}")
        await send(http, cards["quotation_agent"], text)

        print("\n== 3. 用 A2A 呼叫議價顧問，議價顧問再用 A2A 呼叫報價單 Agent")
        for text in ("神盾局科技想把 QT-20260325-001 壓到 200000，可以嗎？", "幫我把 QT-20260325-001 的總價改成 200000"):
            print(f"> {text}")
            await send(http, cards["pricing_advisor"], text)


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")
    asyncio.run(main())
