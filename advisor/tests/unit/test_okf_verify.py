"""報價單資料表的驗證：老師 seed 裡對不上的單要和條目的 seed_mismatches 完全一致（離線，用 seed 檔與假分頁）。"""

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


CONSISTENT = "QT-20260330-001"  # 老師 seed 裡金額和品項一致的一張


def _row(rows, number):
    return next(row for row in rows if row["quotation_number"] == number)


@pytest.mark.asyncio
async def test_teacher_seed_matches_documented_mismatches(bundle_path):
    rows = seed_quotations()
    assert len(rows) == 12
    ctx, concept = context(bundle_path, rows)
    assert concept.frontmatter["seed_mismatches"]["total_price"] == ["QT-20260115-001"]
    ok, notes = await check_quotations_table(ctx, concept)
    assert ok, notes
    assert any("12/12" in note for note in notes)


@pytest.mark.asyncio
@pytest.mark.parametrize("field,bad", [("total_price", "6176"), ("profit_amount", "2376"), ("profit_rate", "0.3847")])
async def test_new_mismatch_on_a_consistent_quotation_fails(bundle_path, field, bad):
    rows = seed_quotations()
    _row(rows, CONSISTENT)[field] = bad
    ctx, concept = context(bundle_path, rows)
    ok, notes = await check_quotations_table(ctx, concept)
    assert not ok
    assert any(CONSISTENT in note for note in notes)


@pytest.mark.asyncio
async def test_fixing_a_documented_mismatch_means_the_concept_is_stale(bundle_path):
    rows = seed_quotations()
    _row(rows, "QT-20260115-001")["total_price"] = "253350"  # 改成重算值，資料和條目就對不起來
    ctx, concept = context(bundle_path, rows)
    ok, notes = await check_quotations_table(ctx, concept)
    assert not ok
    assert any("條目過時" in note for note in notes)


@pytest.mark.asyncio
async def test_profit_rate_rounds_half_up_to_four_places(bundle_path):
    rows = seed_quotations()
    row = _row(rows, CONSISTENT)
    row.update(pricing_factor="1", total_price="200", profit_amount="24.69", profit_rate="0.1235",
               items=[{"list_price": "200", "unit_price": "200", "product_cost": "175.31", "quantity": 1, "subtotal": "200"}])
    ctx, concept = context(bundle_path, rows)
    assert (await check_quotations_table(ctx, concept))[0]
    row["profit_rate"] = "0.1234"  # Half-even would round the exact .12345 tie down.
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
        concept.frontmatter.pop("seed_mismatches")
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
