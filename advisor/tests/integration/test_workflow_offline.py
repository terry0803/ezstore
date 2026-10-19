"""整張 Workflow 的離線整合測試：LLM 換成假模型、後端換成測試資料快照、A2A 對方換成假的。

不需要 API key，也不需要任何服務在跑。
"""

import json
import re
from collections.abc import AsyncGenerator
from decimal import Decimal

import pytest
from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_response import LlmResponse
from google.adk.runners import InMemoryRunner
from google.genai import types

import pricing_advisor.agent as advisor
from pricing_advisor.a2a_client import A2AResult
from tests.conftest import SNAPSHOT, FakeBackend


class FakeLlm(BaseLlm):
    """understand 依使用者這一句回固定的 JSON；answer_with_knowledge 回一段照條目寫的話。"""

    model: str = "fake-llm"
    answer_calls: int = 0

    async def generate_content_async(self, llm_request, stream: bool = False) -> AsyncGenerator[LlmResponse, None]:
        text = "".join(p.text or "" for c in llm_request.contents for p in (c.parts or []))
        if "使用者這一句：" in text:
            line = text.split("使用者這一句：")[-1]
            number = (re.findall(r"QT-\d{8}-\d{3}", line) or [None])[0]
            if "順便" in line:
                # 模擬模型看錯：把夾帶改價的句子判成一般操作
                intent = {"intent": "quotation_request", "quotation_number": number}
            elif "天氣" in line:
                intent = {"intent": "off_topic"}
            elif "多少" in line and "毛利率" in line:
                intent = {"intent": "policy_question", "concept_ids": ["policies/discount-approval"]}
            elif "轉" in line and "訂單" in line:
                intent = {"intent": "convert_order" if "幫我" in line else "order_check", "quotation_number": number}
            elif "幫我改" in line or "改成" in line:
                intent = {"intent": "apply_price", "quotation_number": number}
            elif "壓到" in line:
                intent = {"intent": "price_check", "quotation_number": number}
            elif "查詢" in line or "複製" in line:
                intent = {"intent": "quotation_request", "quotation_number": number}
            else:
                intent = {"intent": "provide_info"}
            reply = json.dumps(intent, ensure_ascii=False)
        else:
            self.answer_calls += 1
            reply = "毛利率 25% 以上業務可以直接調整，15% 到 25% 要業務主管核准，未滿 5% 不可報價。"
        yield LlmResponse(content=types.Content(role="model", parts=[types.Part(text=reply)]))


def _copy_with_factor(quotation, number, factor):
    """模擬報價單 Agent 改價後的新報價單：同樣的品項，換報價因子後重算。"""
    new = json.loads(json.dumps(quotation))
    new.update({"id": 13, "quotation_number": number, "pricing_factor": str(factor)})
    total = Decimal(0)
    for item in new["items"]:
        unit = Decimal(item["list_price"]) * Decimal(str(factor))
        item["unit_price"], item["subtotal"] = str(unit), str(unit * item["quantity"])
        total += unit * item["quantity"]
    new["total_price"] = str(total)
    cost = sum(Decimal(item["product_cost"]) * item["quantity"] for item in new["items"])
    new["profit_amount"] = str(total - cost)
    new["profit_rate"] = str((total - cost) / total)
    return new


class FakeQuotationAgent:
    def __init__(self, backend):
        self.requests = []
        self.backend = backend

    async def send(self, text, on_dispatch=None):
        self.requests.append(text)
        if on_dispatch:
            on_dispatch(f"task-{len(self.requests)}", f"ctx-{len(self.requests)}")
        if "轉訂單" in text:
            number = re.search(r"QT-\d{8}-\d{3}", text).group(0)
            quotation = self.backend.quotations[number]
            self.backend.orders.setdefault(str(quotation["customer_id"]), []).append(
                {"id": 11, "order_number": "ORD-20261017-001", "quotation_id": quotation["id"],
                 "customer_id": quotation["customer_id"], "status": "pending",
                 "total_price": quotation["total_price"], "items": json.loads(json.dumps(quotation["items"]))}
            )
            reply = f"已成功將報價單轉換為訂單。\n報價單: {number}（未修改）\n訂單編號: ORD-20261017-001\n訂單連結: http://localhost:3000/orders/11"
        elif "複製" in text:
            number = re.search(r"QT-\d{8}-\d{3}", text).group(0)
            source = self.backend.quotations[number]
            self.backend.quotations["QT-20261017-001"] = _copy_with_factor(source, "QT-20261017-001", source["pricing_factor"])
            reply = "已複製報價單：QT-20261017-001 http://localhost:3000/quotations/13"
        elif "查詢" in text:
            reply = "報價單查詢完成 http://localhost:3000/quotations/1"
        else:
            self.backend.quotations["QT-20261017-001"] = _copy_with_factor(
                self.backend.quotations["QT-20260325-001"], "QT-20261017-001", "0.7751"
            )
            reply = (
                "已透過二分法調整報價因子使總價逼近目標值。\n"
                "原始報價單: QT-20260325-001（未修改） — http://localhost:3000/quotations/9\n"
                "新報價單: QT-20261017-001\n系統連結: http://localhost:3000/quotations/13"
            )
        return A2AResult(text=reply, task_id="task-1234abcd", context_id="ctx-1", state="completed", agent="quotation_agent")


@pytest.fixture
def runner(monkeypatch):
    # 每個測試使用獨立的程序內轉單保護，避免鎖綁定前一個 event loop 或殘留未明狀態。
    monkeypatch.setattr(advisor, "_CONVERT_LOCKS", {})
    monkeypatch.setattr(advisor, "_CONVERT_UNCERTAIN", {})
    monkeypatch.setattr(advisor, "MODEL", "gemini-3.8-flash")
    monkeypatch.setenv("GEMINI_API_KEY", "offline-test")
    fake_llm = FakeLlm()
    # Workflow 建立時已 clone LlmAgent；必須替換真正執行的圖節點。
    for node in advisor.root_agent.graph.nodes:
        if node.name in ("understand", "answer_with_knowledge"):
            monkeypatch.setattr(node, "model", fake_llm)
    fake_backend = FakeBackend(
        quotations=json.loads(json.dumps(SNAPSHOT["quotations"])),
        orders=json.loads(json.dumps(SNAPSHOT["orders_by_customer"])),
    )
    monkeypatch.setattr(advisor, "backend", fake_backend)
    peer = FakeQuotationAgent(fake_backend)
    monkeypatch.setattr(advisor, "quotation_agent", peer)
    peer.fake_llm = fake_llm
    yield InMemoryRunner(app=advisor.app), peer


async def ask(runner, session_id, text):
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


async def new_session(runner):
    return (await runner.session_service.create_session(app_name="pricing_advisor", user_id="t")).id


@pytest.mark.asyncio
@pytest.mark.parametrize("question", [
    "請幫我確認複製報價單 QT-20260325-001 要多久？",
    "等主管同意後，再把 QT-20260325-001 總價改成 300000",
])
async def test_duration_and_external_consent_clear_pending_without_a2a(runner, question):
    run, peer = runner
    session = await new_session(run)
    await ask(run, session, "幫我複製報價單")
    await ask(run, session, question)
    assert peer.requests == []
    await ask(run, session, "QT-20260325-001")
    assert len(peer.requests) == 1 and "查詢" in peer.requests[0]


@pytest.mark.asyncio
async def test_relative_increase_asks_for_final_total_without_a2a(runner):
    run, peer = runner
    session = await new_session(run)
    reply = await ask(run, session, "幫我把 QT-20260325-001 總價調高 300000")
    assert "目標總價" in reply
    assert peer.requests == []


@pytest.mark.asyncio
@pytest.mark.parametrize("question", [
    "幫我確認 QT-20260330-001 總價改成 8000 是否需要主管核准",
    "幫我複製報價單 QT-20260330-001，需要誰核准",
    "幫我把 QT-20260330-001 轉成訂單，要不要簽核",
])
async def test_approval_question_clears_pending_without_a2a(runner, question):
    run, peer = runner
    session = await new_session(run)
    await ask(run, session, "幫我複製報價單")
    reply = await ask(run, session, question)
    assert ("試算" if "總價" in question else "知識庫") in reply
    assert peer.requests == []
    await ask(run, session, "QT-20260330-001")
    assert len(peer.requests) == 1 and "查詢" in peer.requests[0]


@pytest.mark.asyncio
async def test_copy_missing_number_resumes_through_full_workflow(runner):
    run, peer = runner
    session = await new_session(run)
    before = len(peer.backend.quotations)
    first = await ask(run, session, "幫我複製報價單")
    assert "請提供要複製的報價單編號" in first
    assert peer.requests == []
    second = await ask(run, session, "QT-20260330-001")
    assert "已複製" in second
    assert peer.requests == ["我要複製報價單，報價單編號：QT-20260330-001"]
    assert len(peer.backend.quotations) == before + 1
    await ask(run, session, "QT-20260330-001")
    assert len(peer.requests) == 2 and "查詢" in peer.requests[-1]
    assert len(peer.backend.quotations) == before + 1


@pytest.mark.asyncio
async def test_cancel_copy_clears_pending_in_persisted_session(runner):
    run, peer = runner
    session = await new_session(run)
    before = len(peer.backend.quotations)
    await ask(run, session, "幫我複製報價單")
    await ask(run, session, "不要複製")
    assert peer.requests == []
    await ask(run, session, "QT-20260330-001")
    assert len(peer.requests) == 1 and "查詢" in peer.requests[0]
    assert len(peer.backend.quotations) == before


@pytest.mark.asyncio
async def test_policy_question_cites_knowledge(runner):
    run, _ = runner
    reply = await ask(run, await new_session(run), "毛利率要多少以上業務才能自己改價？")
    assert "25%" in reply
    assert "依據（OKF 知識庫）" in reply
    assert "policies/discount-approval" in reply
    assert "作業示範用的虛構規則" in reply
    # 規則條目有結構化的 frontmatter，答案由程式產生，不再多花一次模型呼叫
    assert "15% 以上、未滿 25%，需業務主管核准" in reply
    assert run_peer_llm(runner).answer_calls == 0


def run_peer_llm(runner):
    return runner[1].fake_llm


@pytest.mark.asyncio
async def test_price_check_then_apply_needs_approval(runner):
    run, peer = runner
    session = await new_session(run)
    reply = await ask(run, session, "神盾局科技想把 QT-20260325-001 壓到 180000，可以嗎？")
    assert "毛利率 32.17% → 20.27%" in reply
    assert "判斷：需業務主管核准" in reply
    assert "試算驗證：通過" in reply
    assert "沒有套用" in reply and "已作廢" in reply
    assert "http://localhost:3000/quotations/9" in reply

    reply = await ask(run, session, "那就幫我改")
    assert "我沒有改資料" in reply
    assert "核准申請（草稿，沒有送出）" in reply
    assert peer.requests == []


@pytest.mark.asyncio
async def test_apply_price_goes_through_a2a(runner):
    run, peer = runner
    reply = await ask(run, await new_session(run), "幫我把 QT-20260325-001 的總價改成 200000")
    assert len(peer.requests) == 1
    marker, payload = peer.requests[0].split('\n', 1)
    assert marker == 'EZSTORE_APPROVED_PRICE_V1'
    guarded = json.loads(payload)
    assert guarded['quotation_number'] == 'QT-20260325-001'
    assert guarded['target_total_price'] == 200000
    assert guarded['approval']['source'] == SNAPSHOT['quotations']['QT-20260325-001']
    assert guarded['approval']['factor'] == '0.7751'
    assert "經 A2A 交給報價單 Agent，task task-123" in reply
    assert "原始報價單: QT-20260325-001（未修改）" in reply
    assert "改完後核對（從後端重新讀 QT-20261017-001）：報價因子 0.7751" in reply
    assert "毛利率 28.24%，依規則業務可直接調整" in reply
    assert "原單 QT-20260325-001 的報價因子還是 0.8200" in reply


@pytest.mark.asyncio
async def test_order_rules(runner):
    run, peer = runner
    session = await new_session(run)
    draft = await ask(run, session, "QT-20260325-001 可以轉訂單嗎？")
    assert "不能轉" in draft and "draft" in draft
    existing = await ask(run, session, "QT-20260115-001 可以轉訂單嗎？")
    assert "ORD-20260118-001" in existing
    converted = await ask(run, session, "幫我把 QT-20260301-001 轉成訂單")
    assert peer.requests == ["我要將報價單轉訂單，報價單編號：QT-20260301-001"]
    assert "改完後核對：後端查得到 ORD-20261017-001，關聯 QT-20260301-001" in converted
    again = await ask(run, session, "QT-20260301-001 可以轉訂單嗎？")
    assert "不能轉" in again and "ORD-20261017-001" in again


@pytest.mark.asyncio
async def test_misclassified_write_never_reaches_a2a(runner):
    run, peer = runner
    reply = await ask(run, await new_session(run), "我要查詢報價單 QT-20260325-001，順便把總價改成 150000")
    assert peer.requests == []
    assert "改成 150000 的試算" in reply and "判斷：不可報價" in reply


@pytest.mark.asyncio
async def test_unreachable_target_is_not_applied(runner):
    run, peer = runner
    reply = await ask(run, await new_session(run), "幫我把 QT-20260330-001 的總價改成 100000")
    assert "32500.00" in reply and "達不到" in reply
    assert peer.requests == []


@pytest.mark.asyncio
async def test_off_topic_and_clarify(runner):
    run, peer = runner
    session = await new_session(run)
    assert "只能協助報價與議價" in await ask(run, session, "今天台北天氣如何？")
    first = await ask(run, session, "QT-20260325-001 壓到多少可以？")
    assert first.startswith("請提供客戶想要的總價")
    second = await ask(run, session, "200000")
    assert "判斷：業務可直接調整" in second
    assert peer.requests == []


@pytest.mark.asyncio
async def test_failed_second_check_cannot_confirm_the_first_quote(runner):
    run, peer = runner
    session = await new_session(run)
    assert "業務可直接調整" in await ask(run, session, "QT-20260325-001 壓到 200000 可以嗎？")
    failed = await ask(run, session, "QT-20990101-001 壓到 250000 可以嗎？")
    assert "找不到" in failed
    confirmation = await ask(run, session, "那就幫我改")
    assert "請提供" in confirmation
    assert peer.requests == []


@pytest.mark.asyncio
async def test_invalid_amount_never_delegates_even_after_successful_check(runner):
    run, peer = runner
    session = await new_session(run)
    await ask(run, session, "QT-20260325-001 壓到 200000 可以嗎？")
    invalid = await ask(run, session, "幫我把 QT-20260325-001 總價改成 -200000")
    assert "大於 0" in invalid
    confirmation = await ask(run, session, "那就幫我改")
    assert "請提供" in confirmation
    assert peer.requests == []


@pytest.mark.asyncio
async def test_concurrent_conversions_of_one_quotation_create_one_order(runner):
    """兩個人同時要轉同一張單：第一次檢查都會通過，排隊後重新檢查，只有一個真的經 A2A 送出。"""
    import asyncio

    run, peer = runner
    original_send = peer.send

    async def slow_send(text, on_dispatch=None):
        await asyncio.sleep(0.2)  # 讓第二個請求在訂單建好之前就通過 order_check
        return await original_send(text, on_dispatch=on_dispatch)

    peer.send = slow_send
    sessions = [await new_session(run), await new_session(run)]
    replies = await asyncio.gather(*(ask(run, s, "幫我把 QT-20260301-001 轉成訂單") for s in sessions))

    assert sum("轉訂單" in r for r in peer.requests) == 1
    done = [r for r in replies if "改完後核對：後端查得到 ORD-20261017-001" in r]
    blocked = [r for r in replies if "送出前重新檢查" in r]
    assert len(done) == 1 and len(blocked) == 1
    assert "這次沒有轉訂單" in blocked[0] and "已經有訂單" in blocked[0]
    quotation = peer.backend.quotations["QT-20260301-001"]
    linked = [o for o in peer.backend.orders[str(quotation["customer_id"])] if o["quotation_id"] == quotation["id"]]
    assert len(linked) == 1
