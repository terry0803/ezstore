import pytest
import asyncio
import copy

import server


@pytest.mark.asyncio
async def test_customer_list_reads_every_page(monkeypatch):
    calls = []

    async def get(path, **params):
        calls.append((path, params))
        if path == "/customers":
            return {"data": [{"id": 7, "name": "測試公司"}], "total": 1}
        rows = [{"id": i, "quotation_number": f"QT-20260330-{i:03d}", "total_price": "100", "status": "draft"} for i in range(1, 102)]
        start = (params["page"] - 1) * params["page_size"]
        return {"data": rows[start:start + params["page_size"]], "total": 101}

    monkeypatch.setattr(server, "_get", get)
    reply = await server.list_customer_quotations("測試公司")
    assert "共 101 筆" in reply
    assert "QT-20260330-101" in reply
    assert [p["page"] for path, p in calls if path == "/quotations"] == [1, 2]


@pytest.mark.asyncio
async def test_customer_lookup_finds_exact_match_on_later_page(monkeypatch):
    async def get(path, **params):
        if params["page"] == 1:
            return {"data": [{"id": i, "name": f"測試公司分店{i}"} for i in range(100)], "total": 101}
        return {"data": [{"id": 101, "name": "測試公司"}], "total": 101}

    monkeypatch.setattr(server, "_get", get)
    assert (await server._find_customer_by_name("測試公司"))["id"] == 101


@pytest.mark.asyncio
@pytest.mark.parametrize(("names", "query"), [
    (["測試甲公司", "測試乙公司"], "測試"),
    (["同名公司", "同名公司"], "同名公司"),
])
async def test_ambiguous_customer_does_not_choose_first(monkeypatch, names, query):
    async def get(*args, **kwargs):
        return {"data": [{"id": i, "name": name} for i, name in enumerate(names, 1)], "total": len(names)}

    monkeypatch.setattr(server, "_get", get)
    with pytest.raises(server.ToolError, match="多位"):
        await server.list_customer_quotations(query)


@pytest.mark.asyncio
@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf"), 0, -1])
@pytest.mark.parametrize("tool", [server.update_pricing_factor, server.adjust_total_price])
async def test_invalid_amount_never_duplicates(monkeypatch, tool, value):
    async def forbidden(*args, **kwargs):
        raise AssertionError("invalid amount must fail before lookup or mutation")

    monkeypatch.setattr(server, "_require_quotation", forbidden)
    monkeypatch.setattr(server, "_duplicate", forbidden)
    with pytest.raises(server.ToolError, match="有限數字"):
        await tool("QT-20260330-001", value)


@pytest.mark.asyncio
async def test_unreachable_total_still_copies_and_reports_actual_total(monkeypatch):
    """講義的流程：先複製再二分，做不到就照實回報實際總價與提醒，原單不動。"""
    original = {"id": 12, "quotation_number": "QT-20260330-001", "pricing_factor": "0.95", "total_price": "6175"}
    copy = {"id": 13, "quotation_number": "QT-20261017-001", "customer_id": 14, "notes": "",
            "items": [{"product_id": 6, "quantity": 10}]}
    calls = {"duplicate": 0}

    async def require(_number):
        return original

    async def duplicate(q):
        assert q is original
        calls["duplicate"] += 1
        return copy

    async def put(path, body, **_kwargs):
        assert path == "/quotations/13"
        factor = body["pricing_factor"]
        return {"id": 13, "quotation_number": copy["quotation_number"], "pricing_factor": factor,
                "total_price": round(factor * 6500, 2)}

    monkeypatch.setattr(server, "_require_quotation", require)
    monkeypatch.setattr(server, "_duplicate", duplicate)
    monkeypatch.setattr(server, "_items_input", lambda q: q["items"])
    monkeypatch.setattr(server, "_put", put)
    text = await server.adjust_total_price("QT-20260330-001", 100000)
    assert calls["duplicate"] == 1
    assert "QT-20260330-001（未修改）" in text
    assert "注意: 已達最大迭代次數" in text
    actual = float(text.split("實際總價: ")[1].split()[0])
    assert 32400 < actual <= 32500


@pytest.mark.asyncio
async def test_repeated_conversion_creates_each_order_and_keeps_source(monkeypatch):
    """第一 Agent 契約允許再次轉單；Advisor 的額外檢查不改 MCP 語意。"""
    original = {"id": 12, "customer_id": 7, "quotation_number": "QT-TEST-001",
                "items": [{"product_id": 3, "unit_price": "12.34", "quantity": 2}]}
    unchanged = copy.deepcopy(original)
    writes = []

    async def require(_number):
        return original

    async def get(path):
        assert path == "/quotations/12"
        return original

    async def post(path, json):
        assert path == "/orders"
        writes.append(copy.deepcopy(json))
        order_id = len(writes)
        await asyncio.sleep(0)
        return {"id": order_id, "order_number": f"ORD-TEST-{order_id:03d}", "total_price": "24.68"}

    monkeypatch.setattr(server, "_require_quotation", require)
    monkeypatch.setattr(server, "_get", get)
    monkeypatch.setattr(server, "_post", post)
    replies = await asyncio.gather(*(server.convert_to_order("QT-TEST-001") for _ in range(2)))
    assert len(writes) == 2
    assert all(body["quotation_id"] == 12 and body["customer_id"] == 7 for body in writes)
    assert all(body["items"] == [{"product_id": 3, "unit_price": 12.34, "quantity": 2}] for body in writes)
    assert "ORD-TEST-001" in replies[0] and "ORD-TEST-002" in replies[1]
    assert original == unchanged


@pytest.mark.asyncio
async def test_factor_change_only_writes_the_duplicate(monkeypatch):
    source = {"id": 12, "quotation_number": "QT-TEST-001", "pricing_factor": "0.9", "total_price": "90"}
    duplicate = {"id": 13, "customer_id": 7, "notes": "copied",
                 "items": [{"product_id": 3, "quantity": 1}]}
    writes = []

    async def require(_number):
        return source

    async def duplicate_q(q):
        assert q is source
        return duplicate

    async def put(path, body):
        writes.append((path, body))
        return {"id": 13, "quotation_number": "QT-TEST-002", "pricing_factor": "0.85", "total_price": "85"}

    monkeypatch.setattr(server, "_require_quotation", require)
    monkeypatch.setattr(server, "_duplicate", duplicate_q)
    monkeypatch.setattr(server, "_put", put)
    reply = await server.update_pricing_factor("QT-TEST-001", 0.85)
    assert len(writes) == 1 and writes[0][0] == "/quotations/13"
    assert writes[0][1]["pricing_factor"] == 0.85
    assert source["pricing_factor"] == "0.9"
    assert "（未修改）" in reply and "QT-TEST-002" in reply
