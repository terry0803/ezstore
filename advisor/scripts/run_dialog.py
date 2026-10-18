"""用真的模型、後端與報價單 Agent（A2A）跑一段對話，印出每一輪的回覆與耗時。

    cd advisor
    uv run python scripts/run_dialog.py                      # 示範對話（會改資料，先重灌 seed）
    uv run python scripts/run_dialog.py "問題一" "問題二"      # 自己的對話

全部在同一個 session 裡，可以測接著問的句子。設定讀 advisor/.env。
"""

import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from google.adk.runners import InMemoryRunner  # noqa: E402
from google.genai import types  # noqa: E402

from pricing_advisor.agent import app  # noqa: E402

DEMO = [
    "毛利率要多少以上，業務才可以自己改價？",
    "神盾局科技想把 QT-20260325-001 壓到 180000，可以嗎？",
    "那就幫我改",
    "如果改成 200000 呢？",
    "好，幫我把 QT-20260325-001 的總價改成 200000",
    "天空之城科技想把 QT-20260328-001 壓到 76000，可以嗎？",
    "QT-20260115-001 可以轉訂單嗎？",
    "幫我把 QT-20260301-001 轉成訂單",
    "今天台北天氣如何？",
]


async def main(turns: list[str]) -> None:
    runner = InMemoryRunner(app=app)
    session = await runner.session_service.create_session(app_name=app.name, user_id="demo")
    for i, text in enumerate(turns, 1):
        start = time.perf_counter()
        reply, path = "", []
        async for ev in runner.run_async(
            user_id="demo",
            session_id=session.id,
            new_message=types.Content(role="user", parts=[types.Part.from_text(text=text)]),
        ):
            node = ev.node_info.path.split("/")[-1] if ev.node_info and ev.node_info.path else ""
            if node and (not path or path[-1] != node):
                path.append(node)
            if node.startswith("respond@") and ev.content and ev.content.parts:
                reply = "".join(p.text or "" for p in ev.content.parts)
        seconds = time.perf_counter() - start
        print(f"\n===== {i}. 使用者：{text}")
        print(f"[{seconds:.1f} 秒] 節點：{' → '.join(p.split('@')[0] for p in path)}")
        print(reply)


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")
    asyncio.run(main(sys.argv[1:] or DEMO))
