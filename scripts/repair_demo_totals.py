"""Plan a one-off repair of the 12 workshop demo quotations; never execute SQL.

Default: GET the API and print a dry-run JSON plan. --snapshot accepts saved API
quotation objects instead. --sql-output creates (never overwrites) a guarded SQL
file for separate review/backup/application. No database credentials or driver.

Pinned source: teacher seed at 09f6588c94ecb74b071246c55c32d838fc31e8f7,
including its final UPDATEs and removal of zero-quantity item 6. Only the known
old totals or already-correct totals are accepted. This is not a general repair.
"""

import argparse
from collections import Counter
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import json
from pathlib import Path
import sys
import urllib.parse
import urllib.request


FIELDS = ("total_price", "profit_amount", "profit_rate")
ITEM_FIELDS = ("product_id", "list_price", "product_cost", "quantity", "unit_price", "subtotal")

# Items: product_id, list_price, product_cost, quantity, unit_price, subtotal.
# All amounts are decimal strings; neither API text nor CLI text becomes SQL.
DEMO = {
    "QT-20260115-001": ("0.7500", ("253500.00", "72000.00", "0.2840"), ("253350.00", "66150.00", "0.2611"), [
        (1, "22000", "12000", 5, "16500", "82500"), (2, "9800", "5500", 20, "7350", "147000"),
        (3, "3500", "1800", 4, "2625", "10500"), (6, "650", "380", 20, "487.50", "9750"),
        (7, "2400", "1200", 2, "1800", "3600")]),
    "QT-20260120-001": ("0.7800", ("278070.00", "82120.00", "0.2953"), ("278070.00", "86570.00", "0.3113"), [
        (11, "15800", "8500", 10, "12324", "123240"), (12, "22500", "12000", 3, "17550", "52650"),
        (13, "65000", "35000", 1, "50700", "50700"), (14, "680", "350", 50, "530.40", "26520"),
        (15, "32000", "18000", 1, "24960", "24960")]),
    "QT-20260205-001": ("0.8800", ("256960.00", "91960.00", "0.3578"), ("256960.00", "91960.00", "0.3579"), [
        (16, "5400", "3200", 30, "4752", "142560"), (17, "1500", "800", 30, "1320", "39600"),
        (18, "85000", "45000", 1, "74800", "74800")]),
    "QT-20260210-001": ("0.8000", ("69320.00", "21320.00", "0.3076"), ("69320.00", "22720.00", "0.3278"), [
        (6, "650", "380", 50, "520", "26000"), (7, "2400", "1200", 10, "1920", "19200"),
        (8, "6800", "3500", 3, "5440", "16320"), (9, "850", "450", 10, "680", "6800"),
        (10, "250", "120", 5, "200", "1000")]),
    "QT-20260218-001": ("0.9000", ("135450.00", "39450.00", "0.2913"), ("135450.00", "52130.00", "0.3849"), [
        (1, "22000", "12000", 2, "19800", "39600"), (2, "9800", "5500", 10, "8820", "88200"),
        (3, "3500", "1800", 2, "3150", "6300"), (10, "250", "120", 6, "225", "1350")]),
    "QT-20260301-001": ("1.0000", ("114000.00", "49000.00", "0.4298"), ("114000.00", "49000.00", "0.4298"), [
        (5, "45000", "25000", 1, "45000", "45000"), (16, "5400", "3200", 10, "5400", "54000"),
        (17, "1500", "800", 10, "1500", "15000")]),
    "QT-20260305-001": ("0.7600", ("194256.00", "57256.00", "0.2948"), ("194256.00", "57256.00", "0.2947"), [
        (20, "28000", "15000", 5, "21280", "106400"), (4, "28000", "15000", 3, "21280", "63840"),
        (11, "15800", "8500", 2, "12008", "24016")]),
    "QT-20260310-001": ("0.9200", ("118680.00", "48680.00", "0.4102"), ("118680.00", "48680.00", "0.4102"), [
        (19, "12000", "6000", 5, "11040", "55200"), (16, "5400", "3200", 10, "4968", "49680"),
        (17, "1500", "800", 10, "1380", "13800")]),
    "QT-20260325-001": ("0.8200", ("211560.00", "66060.00", "0.3123"), ("211560.00", "68060.00", "0.3217"), [
        (1, "22000", "12000", 3, "18040", "54120"), (5, "45000", "25000", 1, "36900", "36900"),
        (2, "9800", "5500", 15, "8036", "120540")]),
    "QT-20260326-001": ("0.9000", ("129960.00", "39960.00", "0.3075"), ("129960.00", "52960.00", "0.4075"), [
        (11, "15800", "8500", 5, "14220", "71100"), (12, "22500", "12000", 2, "20250", "40500"),
        (14, "680", "350", 30, "612", "18360")]),
    "QT-20260328-001": ("1.0000", ("88000.00", "33000.00", "0.3750"), ("88000.00", "38500.00", "0.4375"), [
        (2, "9800", "5500", 5, "9800", "49000"), (16, "5400", "3200", 5, "5400", "27000"),
        (19, "12000", "6000", 1, "12000", "12000")]),
    "QT-20260330-001": ("0.9500", ("6175.00", "2375.00", "0.3846"), ("6175.00", "2375.00", "0.3846"), [
        (6, "650", "380", 10, "617.50", "6175")]),
}


class RepairRefused(ValueError):
    """Input differs from the pinned demo; no repair SQL should be produced."""


def number(value):
    if isinstance(value, bool):
        raise RepairRefused("Boolean is not a numeric demo value")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise RepairRefused("Invalid numeric demo value") from exc
    if not result.is_finite():
        raise RepairRefused("Non-finite numeric demo value")
    return result


def item_multiset(items):
    if not isinstance(items, list):
        raise RepairRefused("Quotation must contain its complete items list")
    rows = []
    for item in items:
        if not isinstance(item, dict) or item.get("deleted_at") is not None:
            raise RepairRefused("Invalid or deleted item")
        try:
            rows.append(tuple(number(item[key]) for key in ITEM_FIELDS))
        except KeyError as exc:
            raise RepairRefused(f"Missing item field: {exc.args[0]}") from exc
    return Counter(rows)


def build_plan(quotations):
    """Validate all twelve before returning any write plan; ignore unrelated IDs."""
    if not isinstance(quotations, list):
        raise RepairRefused("Expected a list of complete quotation objects")
    indexed = {}
    for quote in quotations:
        if not isinstance(quote, dict):
            raise RepairRefused("Invalid quotation object")
        key = quote.get("quotation_number")
        if key in DEMO:
            if key in indexed:
                raise RepairRefused(f"Duplicate demo quotation: {key}")
            indexed[key] = quote
    if set(indexed) != set(DEMO):
        raise RepairRefused("All 12 pinned demo quotations are required")
    changes, skipped = [], []
    for key, (factor, old, new, items) in DEMO.items():
        quote = indexed[key]
        try:
            if quote.get("deleted_at") is not None or number(quote["pricing_factor"]) != number(factor):
                raise RepairRefused(f"{key}: deleted or pricing factor changed")
            expected = Counter(tuple(number(v) for v in item) for item in items)
            if item_multiset(quote.get("items")) != expected:
                raise RepairRefused(f"{key}: items differ from original demo seed")
            current = tuple(number(quote[field]) for field in FIELDS)
        except KeyError as exc:
            raise RepairRefused(f"{key}: missing field {exc.args[0]}") from exc
        if current == tuple(map(number, new)):
            skipped.append(key)
        elif current == tuple(map(number, old)):
            changes.append({"quotation_number": key, "old": dict(zip(FIELDS, old)), "new": dict(zip(FIELDS, new))})
        else:
            raise RepairRefused(f"{key}: stored values are neither original nor already corrected")
    return {"mode": "dry-run", "checked": 12, "expected_updates": len(changes), "changes": changes, "already_correct": skipped}


def guarded_sql(plan):
    """Emit only pinned literals; a modified or externally supplied plan is rejected."""
    keys = [entry["quotation_number"] for entry in plan["changes"]]
    if len(keys) != len(set(keys)) or any(key not in DEMO for key in keys):
        raise RepairRefused("Invalid repair plan")
    for entry in plan["changes"]:
        _, old, new, _ = DEMO[entry["quotation_number"]]
        if entry["old"] != dict(zip(FIELDS, old)) or entry["new"] != dict(zip(FIELDS, new)) or old == new:
            raise RepairRefused("Plan values differ from pinned repair")
    sql = ["-- Generated demo-only repair. Back up the database before separate application.",
           "-- Stops and rolls back on missing rows, changed items, factors, or old totals.",
           f"-- Expected updated quotations: {len(keys)}. No timestamps or item fields are changed.",
           "BEGIN;", "SET LOCAL lock_timeout = '5s';", "SET LOCAL statement_timeout = '30s';",
           "DO $demo_repair$", "DECLARE demo_id bigint; changed integer; repaired integer := 0;", "BEGIN"]
    columns = ", ".join(ITEM_FIELDS)
    for key in keys:
        factor, old, new, items = DEMO[key]
        values = ",\n          ".join("(" + ", ".join(str(v) for v in item) + ")" for item in items)
        assignments = ", ".join(f"{field} = {value}" for field, value in zip(FIELDS, new))
        guards = " AND ".join(f"{field} = {value}" for field, value in zip(FIELDS, old))
        sql.append(f"""  -- {key}: old {old}; new {new}
  SELECT id INTO demo_id FROM public.quotations
    WHERE quotation_number = '{key}' AND deleted_at IS NULL FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'Missing demo quotation: {key}'; END IF;
  -- Lock existing active items; parent FOR UPDATE also blocks new FK-linked items.
  PERFORM id FROM public.quotation_items
    WHERE quotation_id = demo_id AND deleted_at IS NULL FOR UPDATE;
  IF EXISTS (
    WITH expected({columns}) AS (VALUES
          {values})
    SELECT 1 FROM (
      (SELECT {columns} FROM public.quotation_items
        WHERE quotation_id = demo_id AND deleted_at IS NULL
       EXCEPT ALL SELECT {columns} FROM expected)
      UNION ALL
      (SELECT {columns} FROM expected
       EXCEPT ALL SELECT {columns} FROM public.quotation_items
        WHERE quotation_id = demo_id AND deleted_at IS NULL)
    ) AS item_differences
  ) THEN RAISE EXCEPTION 'Demo items changed: {key}'; END IF;
  UPDATE public.quotations SET {assignments}
    WHERE id = demo_id AND quotation_number = '{key}' AND deleted_at IS NULL
      AND pricing_factor = {factor} AND {guards};
  GET DIAGNOSTICS changed = ROW_COUNT;
  IF changed <> 1 THEN RAISE EXCEPTION 'Expected one unchanged demo row: {key}, got %', changed; END IF;
  repaired := repaired + changed;""")
    sql.extend([f"  IF repaired <> {len(keys)} THEN RAISE EXCEPTION 'Unexpected total repair count: %', repaired; END IF;",
                "END;", "$demo_repair$;", "COMMIT;", ""])
    return "\n".join(sql)


def fetch_quotations(api_base):
    """Read only: one exact-number lookup and detail GET per pinned quotation."""
    parsed = urllib.parse.urlparse(api_base)
    if parsed.scheme not in ("http", "https") or not parsed.netloc or parsed.query or parsed.fragment:
        raise RepairRefused("API base must be an HTTP(S) base URL without query/fragment")
    base = api_base.rstrip("/")

    def get(path):
        req = urllib.request.Request(base + path, headers={"Accept": "application/json"}, method="GET")
        with urllib.request.urlopen(req, timeout=15) as response:
            return json.load(response)

    result = []
    for key in DEMO:
        listing = get("/quotations?" + urllib.parse.urlencode({"quotation_number": key, "page_size": 100}))
        rows = listing.get("data", []) if isinstance(listing, dict) else []
        if len(rows) != 1 or rows[0].get("quotation_number") != key:
            raise RepairRefused(f"{key}: API lookup did not return exactly one matching row")
        ident = rows[0].get("id")
        if type(ident) is not int or ident <= 0:
            raise RepairRefused(f"{key}: invalid API ID")
        detail = get(f"/quotations/{ident}")
        if isinstance(detail, dict) and isinstance(detail.get("data"), dict):
            detail = detail["data"]
        if not isinstance(detail, dict) or detail.get("quotation_number") != key or detail.get("id") != ident:
            raise RepairRefused(f"{key}: API detail identity mismatch")
        result.append(detail)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--api-base", default="http://127.0.0.1:8080/api/v1")
    source.add_argument("--snapshot", type=Path, help="JSON list, or {quotations: list/dict}, containing all 12 full API objects")
    parser.add_argument("--sql-output", type=Path, help="Create a guarded SQL file; never executes SQL or overwrites a file")
    args = parser.parse_args(argv)
    try:
        if args.snapshot:
            raw = json.loads(args.snapshot.read_text(encoding="utf-8-sig"))
            quotations = raw.get("quotations", raw) if isinstance(raw, dict) else raw
            if isinstance(quotations, dict):
                quotations = list(quotations.values())
        else:
            quotations = fetch_quotations(args.api_base)
        plan = build_plan(quotations)
        sql = guarded_sql(plan) if args.sql_output else None
        if args.sql_output:
            with args.sql_output.open("x", encoding="utf-8", newline="\n") as output:
                output.write(sql)
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        return 0
    except (RepairRefused, OSError, ValueError, TypeError, KeyError) as exc:
        print(f"Repair refused; no database writes: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
