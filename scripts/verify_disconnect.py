"""在隔離環境（ezstore-fix-test）實際停掉服務，看 Agent 怎麼回、資料有沒有亂掉、服務回來後能不能接著用。

隔離環境的 compose 檔由 artifacts/fix-20261017/compose.test.yml 改成 Gemini（GEMINI_API_KEY 從環境變數帶入），
用環境變數 COMPOSE_FILE 指過去。跑之前先替隔離資料庫灌 seed。
    cd mcp_server && COMPOSE_FILE=... uv run python ../scripts/verify_disconnect.py [backend mcp pause pause_agent a2a]
結果寫到 artifacts/fix-20261017/disconnect-result.json。
"""
import asyncio
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

API = "http://127.0.0.1:58080/api/v1"
AGENT = "http://127.0.0.1:58501"
ADVISOR = "http://127.0.0.1:58502"
MCP = "http://127.0.0.1:58010/mcp"
OUT = Path(__file__).resolve().parents[1] / "artifacts" / "fix-20261017" / "disconnect-result.json"
COMPOSE = ["docker", "compose", "-f", os.environ["COMPOSE_FILE"]]
report = []


def compose(*args):
    subprocess.run(COMPOSE + list(args), check=True, capture_output=True)


def wait_healthy(url, seconds=120):
    deadline = time.time() + seconds
    while time.time() < deadline:
        try:
            if httpx.get(url, timeout=3).status_code < 500:
                return True
        except httpx.HTTPError:
            pass
        time.sleep(1)
    return False


def counts():
    q = httpx.get(API + "/quotations", params={"page_size": 1}, timeout=10).json()["total"]
    o = httpx.get(API + "/orders", params={"page_size": 1}, timeout=10).json()["total"]
    return q, o


def ask(base, app, text, session=None, timeout=300):
    if session is None:
        session = httpx.post(f"{base}/apps/{app}/users/dc/sessions", json={}, timeout=30).json()["id"]
    events = httpx.post(f"{base}/run", json={"app_name": app, "user_id": "dc", "session_id": session,
                                            "new_message": {"role": "user", "parts": [{"text": text}]}},
                        timeout=timeout)
    if events.status_code != 200:
        return session, f"[HTTP {events.status_code}] {events.text[:300]}"
    texts = [p.get("text") for e in events.json() for p in (e.get("content") or {}).get("parts", [])
             if p.get("text") and e.get("author") != "user"]
    return session, (texts[-1] if texts else "[沒有回覆]")


def record(name, ok, **info):
    report.append({"case": name, "ok": ok, **info})
    print(("通過" if ok else "失敗"), name)
    for k, v in info.items():
        print(f"    {k}: {str(v)[:400]}")


# 1. 後端停掉：查詢和改因子
def backend_down():
    before = counts()
    compose("stop", "backend")
    try:
        _, read = ask(AGENT, "quotation_agent", "我要查詢報價單，報價單編號：QT-20260330-001")
        time.sleep(5)
        _, write = ask(AGENT, "quotation_agent", "我要修改報價單報價因子，報價單編號：QT-20260330-001，報價因子改為 1.3")
    finally:
        compose("start", "backend")
        wait_healthy("http://127.0.0.1:58080/health")
    after = counts()
    time.sleep(5)
    _, again = ask(AGENT, "quotation_agent", "我要查詢報價單，報價單編號：QT-20260330-001")
    record("後端停掉時查詢與改因子", "操作失敗" in read and "操作失敗" in write and before == after
           and "QT-20260330-001" in again and "/quotations/12" in again,
           查詢=read, 改因子=write, 資料筆數前後=(before, after), 後端回來再查詢=again[:120])


# 2. MCP 停掉，再啟動，看 Agent 能不能重新連上
def mcp_down():
    compose("stop", "mcp-server")
    try:
        _, down = ask(AGENT, "quotation_agent", "我要查詢報價單，報價單編號：QT-20260330-001")
    finally:
        compose("start", "mcp-server")
        time.sleep(8)
    time.sleep(5)
    _, back = ask(AGENT, "quotation_agent", "我要查詢報價單，報價單編號：QT-20260330-001")
    record("MCP 停掉再啟動", ("連不到" in down or "操作失敗" in down or "操作中斷" in down) and "/quotations/12" in back,
           停掉時=down, 啟動後=back[:150])


# 3. 改總價途中把後端暫停（docker pause），MCP 的請求會逾時
async def mcp_adjust(target):
    async with streamable_http_client(MCP) as streams:
        async with ClientSession(streams[0], streams[1]) as session:
            await session.initialize()
            r = await session.call_tool("adjust_total_price", {"quotation_number": "QT-20260330-001",
                                                               "target_total_price": target})
            return r.is_error, r.content[0].text


def pause_on_first_put(container, flag):
    proc = subprocess.Popen(["docker", "logs", "-f", "--since", "1s", container], stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
    for line in proc.stdout:
        if "PUT" in line and "/api/v1/quotations/" in line:
            subprocess.run(["docker", "pause", container], capture_output=True)
            flag["paused_at"] = line.strip()
            break
    proc.kill()


def mid_operation_pause():
    container = "ezstore-fix-test-backend-1"
    before = counts()
    flag = {}
    watcher = threading.Thread(target=pause_on_first_put, args=(container, flag), daemon=True)
    watcher.start()
    time.sleep(1.5)
    started = time.time()
    try:
        is_error, text = asyncio.run(mcp_adjust(9000))
    finally:
        subprocess.run(["docker", "unpause", container], capture_output=True)
    wait_healthy("http://127.0.0.1:58080/health")
    after = counts()
    record("改總價途中後端暫停", is_error and after[0] == before[0] + 1,
           在哪一個請求暫停=flag.get("paused_at"), MCP回覆=text, 秒數=round(time.time() - started, 1),
           報價單筆數前後=(before[0], after[0]), 說明="複製單已建立但總價沒調完；要看 Agent 有沒有提醒使用者去查")


# 4. 同樣情況經過 Agent：看回覆有沒有提醒使用者先查詢
def mid_operation_via_agent():
    container = "ezstore-fix-test-backend-1"
    flag = {}
    watcher = threading.Thread(target=pause_on_first_put, args=(container, flag), daemon=True)
    watcher.start()
    time.sleep(1.5)
    try:
        _, reply = ask(AGENT, "quotation_agent", "我要修改報價單總價，報價單編號：QT-20260330-001，總價改為 9000")
    finally:
        subprocess.run(["docker", "unpause", container], capture_output=True)
    wait_healthy("http://127.0.0.1:58080/health")
    record("經 Agent 改總價途中後端暫停", ("查詢" in reply and "確認" in reply), 在哪一個請求暫停=flag.get("paused_at"), 回覆=reply)


# 5. 議價顧問要經 A2A 改價時，報價單 Agent 停掉
def a2a_peer_down():
    before = counts()
    compose("stop", "agent")
    try:
        _, reply = ask(ADVISOR, "pricing_advisor", "幫我把 QT-20260325-001 的總價改成 200000")
    finally:
        compose("start", "agent")
        wait_healthy("http://127.0.0.1:58501/list-apps")
    after = counts()
    record("A2A 對方停掉", before == after and ("A2A" in reply or "報價單 Agent" in reply) and "改完後核對（" not in reply,
           回覆=reply, 資料筆數前後=(before, after))


if __name__ == "__main__":
    steps = {"backend": backend_down, "mcp": mcp_down, "pause": mid_operation_pause,
             "pause_agent": mid_operation_via_agent, "a2a": a2a_peer_down}
    for name in (sys.argv[1:] or steps):
        try:
            steps[name]()
        except Exception as exc:  # 測試本身出錯也要留紀錄
            record(name, False, 例外=repr(exc))
        time.sleep(5)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    sys.exit(0 if all(r["ok"] for r in report) else 1)
