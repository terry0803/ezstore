import pytest

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
