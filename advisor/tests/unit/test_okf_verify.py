"""Current-data verification against offline seed data and mocked pagination."""

import copy
import csv
from pathlib import Path
import re
from unittest.mock import AsyncMock, call

import pytest

from pricing_advisor.okf import Bundle
from pricing_advisor.okf_verify import VerifyContext, check_quotations_table


ROOT = Path(__file__).resolve().parents[3]


def seed_quotations():
    """Read the checked-in demo SQL as data; never connect to a database."""
    text = (ROOT / "scripts/seed-test-data.sql").read_text(encoding="utf-8")
    tables = {"quotations": {}, "quotation_items": {}}
    pattern = r"INSERT INTO (quotations|quotation_items) \(([^\n]+)\) VALUES\s*\n(.*?);"
    for match in re.finditer(pattern, text, re.S):
        table, columns, block = match.groups()
        fields = [field.strip() for field in columns.split(",")]
        for line in block.splitlines():
            line = line.strip()
            if not line.startswith("("):
                continue
            row = re.fullmatch(r"\((.*)\),?", line)
            values = next(csv.reader([row.group(1)], quotechar="'", skipinitialspace=True))
            item = dict(zip(fields, values))
            tables[table][item["id"]] = item
    for match in re.finditer(r"UPDATE quotations SET ([^;]+) WHERE id = (\d+);", text):
        for assignment in match[1].split(","):
            key, value = assignment.strip().split(" = ")
            tables["quotations"][match[2]][key] = value
    for match in re.finditer(r"DELETE FROM quotation_items WHERE id = (\d+);", text):
        tables["quotation_items"].pop(match[1], None)
    for quote in tables["quotations"].values():
        quote["items"] = [copy.deepcopy(item) for item in tables["quotation_items"].values() if item["quotation_id"] == quote["id"]]
        quote["id"] = int(quote["id"])
        for item in quote["items"]:
            item["quantity"] = int(item["quantity"])
    return list(tables["quotations"].values())


def context(bundle_path, rows):
    ctx = VerifyContext(Bundle(bundle_path), ROOT, "http://offline.invalid", "http://offline.invalid/mcp", "http://offline.invalid/agent")
    ctx.get = AsyncMock(return_value={"data": rows, "total": len(rows), "page": 1})
    return ctx, ctx.bundle.get("system/quotations-table")


@pytest.mark.asyncio
async def test_corrected_seed_all_twelve_are_consistent(bundle_path):
    rows = seed_quotations()
    assert len(rows) == 12
    ctx, concept = context(bundle_path, rows)
    assert concept.frontmatter["derived_amounts_consistent"] is True
    ok, notes = await check_quotations_table(ctx, concept)
    assert ok
    assert any("12/12" in note for note in notes)


@pytest.mark.asyncio
@pytest.mark.parametrize("field,bad", [("total_price", "253500"), ("profit_amount", "72000"), ("profit_rate", "0.2840")])
async def test_polluted_derived_value_fails(bundle_path, field, bad):
    rows = seed_quotations()
    rows[0][field] = bad
    ctx, concept = context(bundle_path, rows)
    ok, notes = await check_quotations_table(ctx, concept)
    assert not ok
    assert any("QT-20260115-001" in note for note in notes)


@pytest.mark.asyncio
async def test_historical_one_total_seven_profits_is_not_a_passing_state(bundle_path):
    rows = seed_quotations()
    old_profits = {
        "QT-20260115-001": "72000", "QT-20260120-001": "82120",
        "QT-20260210-001": "21320", "QT-20260218-001": "39450",
        "QT-20260325-001": "66060", "QT-20260326-001": "39960", "QT-20260328-001": "33000",
    }
    for quote in rows:
        if quote["quotation_number"] in old_profits:
            quote["profit_amount"] = old_profits[quote["quotation_number"]]
    rows[0]["total_price"] = "253500"
    ctx, concept = context(bundle_path, rows)
    assert not (await check_quotations_table(ctx, concept))[0]


@pytest.mark.asyncio
async def test_profit_rate_rounds_half_up_to_four_places(bundle_path):
    rows = seed_quotations()
    rows[0].update(pricing_factor="1", total_price="200", profit_amount="24.69", profit_rate="0.1235",
                   items=[{"list_price": "200", "unit_price": "200", "product_cost": "175.31", "quantity": 1, "subtotal": "200"}])
    ctx, concept = context(bundle_path, rows)
    assert (await check_quotations_table(ctx, concept))[0]
    rows[0]["profit_rate"] = "0.1234"  # Half-even would round the exact .12345 tie down.
    assert not (await check_quotations_table(ctx, concept))[0]


@pytest.mark.asyncio
@pytest.mark.parametrize("problem", ["missing", "duplicate", "empty_items", "not_finite", "missing_claim"])
async def test_incomplete_evidence_never_passes(bundle_path, problem):
    rows = seed_quotations()
    if problem == "missing":
        rows.pop()
    elif problem == "duplicate":
        rows[-1]["quotation_number"] = rows[0]["quotation_number"]
    elif problem == "empty_items":
        rows[0]["items"] = []
    elif problem == "not_finite":
        rows[0]["profit_rate"] = "NaN"
    ctx, concept = context(bundle_path, rows)
    if problem == "missing_claim":
        concept.frontmatter.pop("derived_amounts_consistent")
    assert not (await check_quotations_table(ctx, concept))[0]


@pytest.mark.asyncio
async def test_101_rows_include_second_page_and_are_cached_only_when_complete(bundle_path):
    rows = [{"id": i, "quotation_number": f"QT-20261017-{i:03d}"} for i in range(1, 90)]
    demo = seed_quotations()
    for ident, quote in enumerate(demo, 90):
        quote["id"] = ident
    rows.extend(demo)
    ctx, concept = context(bundle_path, rows)
    ctx.get = AsyncMock(side_effect=[
        {"data": rows[:100], "total": 101, "page": 1},
        {"data": rows[100:], "total": 101, "page": 2},
    ])
    assert (await check_quotations_table(ctx, concept))[0]
    assert len(await ctx.quotations()) == 101
    assert ctx.get.call_args_list == [call("/quotations", page=1, page_size=100), call("/quotations", page=2, page_size=100)]
    # The twelfth seed quotation is on page 2; its bad value must still be caught.
    rows[-1]["profit_amount"] = "0"
    assert not (await check_quotations_table(ctx, concept))[0]


@pytest.mark.asyncio
@pytest.mark.parametrize("second_page", [
    {"data": [], "total": 101, "page": 2},
    {"data": [{"id": 1}], "total": 101, "page": 2},
    {"data": [{"id": 101}], "total": 102, "page": 2},
])
async def test_broken_pagination_fails_without_caching_partial_data(bundle_path, second_page):
    first = [{"id": i} for i in range(1, 101)]
    ctx, _ = context(bundle_path, first)
    ctx.get = AsyncMock(side_effect=[{"data": first, "total": 101, "page": 1}, second_page])
    with pytest.raises(ValueError):
        await ctx.quotations()
    assert "quotations" not in ctx._cache
