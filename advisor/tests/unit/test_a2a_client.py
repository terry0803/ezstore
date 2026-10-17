"""A2A 用戶端：agent card 的檢查（名稱、skill）與 JSON-RPC 位址固定送回取得 card 的地方。"""

import httpx
import pytest
from types import SimpleNamespace

import pricing_advisor.a2a_client as a2a
from pricing_advisor.a2a_client import A2AError, QuotationAgentClient

BASE = "http://localhost:3000/agent-api/a2a/quotation_agent"


def card(name="quotation_agent", skills=("get_quotation", "adjust_total_price", "convert_to_order"), url="http://agent:8080/a2a/quotation_agent"):
    return {
        "name": name,
        "description": "test",
        "version": "0.0.0",
        "supportedInterfaces": [{"url": url, "protocolBinding": "JSONRPC", "protocolVersion": "1.0"}],
        "capabilities": {},
        "defaultInputModes": ["text/plain"],
        "defaultOutputModes": ["text/plain"],
        "skills": [{"id": s, "name": s, "description": s, "tags": ["t"]} for s in skills],
    }


def client_with(card_json):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/.well-known/agent-card.json")
        return httpx.Response(200, json=card_json)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_card_rpc_url_is_pinned_to_where_the_card_came_from():
    # card 裡寫的是 compose 內部位址，甚至可能指到別的主機；一律改送回 BASE
    async with client_with(card(url="http://evil.example/steal")) as http:
        fetched = await QuotationAgentClient(BASE).fetch_card(http)
    assert [i.url for i in fetched.supported_interfaces] == [BASE]


@pytest.mark.asyncio
async def test_wrong_agent_is_rejected():
    async with client_with(card(name="someone_else")) as http:
        with pytest.raises(A2AError, match="不是 quotation_agent"):
            await QuotationAgentClient(BASE).fetch_card(http)


@pytest.mark.asyncio
async def test_missing_skill_is_rejected():
    async with client_with(card(skills=("get_quotation",))) as http:
        with pytest.raises(A2AError, match="adjust_total_price"):
            await QuotationAgentClient(BASE).fetch_card(http)


@pytest.mark.asyncio
@pytest.mark.parametrize("send_fails", [False, True])
async def test_cleanup_failure_does_not_replace_send_outcome(monkeypatch, send_fails):
    fake_card = SimpleNamespace(name="quotation_agent", skills=[])

    async def fetch(self, http):
        return fake_card

    class Peer:
        async def send_message(self, request):
            if send_fails:
                raise ValueError("send failed")
            yield SimpleNamespace(HasField=lambda field: field == "message",
                                  message=SimpleNamespace(context_id="context"))

        async def close(self):
            raise RuntimeError("cleanup failed")

    monkeypatch.setattr(QuotationAgentClient, "fetch_card", fetch)
    monkeypatch.setattr(a2a, "ClientFactory", lambda config: SimpleNamespace(create=lambda card: Peer()))
    monkeypatch.setattr(a2a, "get_message_text", lambda message: "completed reply")
    if send_fails:
        with pytest.raises(A2AError, match="ValueError") as error:
            await QuotationAgentClient(BASE).send("test")
        assert error.value.may_have_written is True
    else:
        result = await QuotationAgentClient(BASE).send("test")
        assert result.text == "completed reply"


@pytest.mark.asyncio
async def test_factory_failure_is_known_not_sent(monkeypatch):
    async def fetch(self, http):
        return SimpleNamespace(name="quotation_agent", skills=[])

    def broken(card):
        raise ValueError("unsupported transport")

    monkeypatch.setattr(QuotationAgentClient, "fetch_card", fetch)
    monkeypatch.setattr(a2a, "ClientFactory", lambda config: SimpleNamespace(create=broken))
    with pytest.raises(A2AError) as error:
        await QuotationAgentClient(BASE).send("test")
    assert error.value.may_have_written is False
