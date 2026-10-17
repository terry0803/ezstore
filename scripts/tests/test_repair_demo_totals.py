"""Offline tests: fake API responses and temporary output files only."""

from contextlib import redirect_stdout, redirect_stderr
import copy
from decimal import Decimal, ROUND_HALF_UP
import importlib.util
import io
import json
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch


SPEC = importlib.util.spec_from_file_location("repair_demo_totals", Path(__file__).resolve().parents[1] / "repair_demo_totals.py")
repair = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(repair)


def demo_snapshot(corrected=False):
    quotes = []
    for ident, (key, (factor, old, new, items)) in enumerate(repair.DEMO.items(), 1):
        quotes.append({
            "id": ident, "quotation_number": key, "pricing_factor": factor,
            **dict(zip(repair.FIELDS, new if corrected else old)),
            "items": [dict(zip(repair.ITEM_FIELDS, item)) for item in items],
        })
    return quotes


class DemoRepairTests(unittest.TestCase):
    def test_pinned_corrections_recompute_from_original_items(self):
        self.assertEqual(len(repair.DEMO), 12)
        for key, (factor, old, new, items) in repair.DEMO.items():
            with self.subTest(quotation=key):
                total = sum(Decimal(item[5]) for item in items)
                profit = sum((Decimal(item[4]) - Decimal(item[2])) * item[3] for item in items)
                rate = (profit / total).quantize(Decimal("0.0001"), ROUND_HALF_UP)
                self.assertEqual(tuple(map(Decimal, new)), (total, profit, rate))
                for product, price, cost, qty, unit, subtotal in items:
                    self.assertEqual(Decimal(price) * Decimal(factor), Decimal(unit))
                    self.assertEqual(Decimal(unit) * qty, Decimal(subtotal))

    def test_original_demo_plans_nine_repairs_and_three_skips(self):
        snapshot = demo_snapshot()
        before = copy.deepcopy(snapshot)
        plan = repair.build_plan(snapshot)
        self.assertEqual(plan["expected_updates"], 9)
        self.assertEqual(plan["already_correct"], ["QT-20260301-001", "QT-20260310-001", "QT-20260330-001"])
        self.assertEqual(snapshot, before)

    def test_corrected_demo_is_noop(self):
        plan = repair.build_plan(demo_snapshot(corrected=True))
        self.assertEqual(plan["expected_updates"], 0)
        self.assertNotIn("UPDATE public.quotations", repair.guarded_sql(plan))

    def test_partially_repaired_database_skips_correct_rows(self):
        snapshot = demo_snapshot()
        snapshot[0].update(zip(repair.FIELDS, repair.DEMO[snapshot[0]["quotation_number"]][2]))
        self.assertEqual(repair.build_plan(snapshot)["expected_updates"], 8)

    def test_changed_item_field_refuses_whole_plan(self):
        for field in repair.ITEM_FIELDS:
            with self.subTest(field=field):
                snapshot = demo_snapshot()
                snapshot[-1]["items"][0][field] = str(Decimal(str(snapshot[-1]["items"][0][field])) + 1)
                with self.assertRaisesRegex(repair.RepairRefused, "items differ"):
                    repair.build_plan(snapshot)

    def test_missing_or_extra_item_refuses_even_if_totals_look_original(self):
        for operation in ("remove", "duplicate"):
            with self.subTest(operation=operation):
                snapshot = demo_snapshot()
                if operation == "remove":
                    snapshot[0]["items"].pop()
                else:
                    snapshot[0]["items"].append(copy.deepcopy(snapshot[0]["items"][0]))
                with self.assertRaises(repair.RepairRefused):
                    repair.build_plan(snapshot)

    def test_changed_factor_or_unexpected_old_value_refuses(self):
        for field in ("pricing_factor", *repair.FIELDS):
            with self.subTest(field=field):
                snapshot = demo_snapshot()
                snapshot[0][field] = "123.4567"
                with self.assertRaises(repair.RepairRefused):
                    repair.build_plan(snapshot)

    def test_requires_all_twelve_exactly_once(self):
        for snapshot in (demo_snapshot()[:6], demo_snapshot() + demo_snapshot()[:1]):
            with self.assertRaises(repair.RepairRefused):
                repair.build_plan(snapshot)

    def test_numeric_equivalence_and_item_order_are_safe(self):
        snapshot = demo_snapshot()
        snapshot[0]["items"].reverse()
        snapshot[0]["items"][0]["unit_price"] = "1800.0000"
        self.assertEqual(repair.build_plan(snapshot)["expected_updates"], 9)

    def test_invalid_numeric_values_refuse(self):
        for value in ("NaN", "Infinity", True, "1; DROP TABLE quotations"):
            snapshot = demo_snapshot()
            snapshot[0]["items"][0]["subtotal"] = value
            with self.assertRaises(repair.RepairRefused):
                repair.build_plan(snapshot)

    def test_sql_has_only_pinned_three_field_updates_and_transaction_guards(self):
        sql = repair.guarded_sql(repair.build_plan(demo_snapshot()))
        self.assertIn("BEGIN;", sql)
        self.assertTrue(sql.endswith("END;\n$demo_repair$;\nCOMMIT;\n"))
        updates = re.findall(r"UPDATE public\.quotations SET ([^\n]+)", sql)
        self.assertEqual(len(updates), 9)
        for assignments in updates:
            self.assertEqual([part.split(" = ")[0] for part in assignments.split(", ")], list(repair.FIELDS))
        self.assertEqual(sql.count("GET DIAGNOSTICS changed = ROW_COUNT;"), 9)
        self.assertEqual(sql.count("IF changed <> 1 THEN RAISE EXCEPTION"), 9)
        self.assertEqual(sql.count("EXCEPT ALL"), 18)
        self.assertIn("AND total_price = 253500.00 AND profit_amount = 72000.00 AND profit_rate = 0.2840", sql)
        self.assertIn("IF repaired <> 9 THEN", sql)
        self.assertNotIn("updated_at", sql)
        for command in ("TRUNCATE", "DELETE FROM", "ALTER TABLE", "INSERT INTO"):
            self.assertNotIn(command, sql)

    def test_tampered_plan_cannot_inject_sql(self):
        plan = repair.build_plan(demo_snapshot())
        plan["changes"][0]["new"]["total_price"] = "0; DROP TABLE quotations"
        with self.assertRaises(repair.RepairRefused):
            repair.guarded_sql(plan)

    def test_api_fetch_uses_only_get_and_validates_identity(self):
        fixtures = demo_snapshot()
        requests = []

        def fake_urlopen(request, timeout):
            requests.append(request)
            if "?" in request.full_url:
                query = repair.urllib.parse.parse_qs(repair.urllib.parse.urlparse(request.full_url).query)
                matching = [q for q in fixtures if q["quotation_number"] == query["quotation_number"][0]]
                data = {"data": [{"id": q["id"], "quotation_number": q["quotation_number"]} for q in matching]}
            else:
                ident = int(request.full_url.rsplit("/", 1)[1])
                data = fixtures[ident - 1]
            return io.BytesIO(json.dumps(data).encode())

        with patch.object(repair.urllib.request, "urlopen", side_effect=fake_urlopen):
            result = repair.fetch_quotations("http://fake.invalid/api/v1")
        self.assertEqual(result, fixtures)
        self.assertEqual(len(requests), 24)
        self.assertTrue(all(request.get_method() == "GET" and request.data is None for request in requests))

    def test_dry_run_never_writes_and_sql_output_never_overwrites(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            snapshot = root / "snapshot.json"
            snapshot.write_text(json.dumps(demo_snapshot()), encoding="utf-8")
            output = root / "repair.sql"
            with patch.object(repair.urllib.request, "urlopen", side_effect=AssertionError("No network")):
                with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                    self.assertEqual(repair.main(["--snapshot", str(snapshot)]), 0)
                    self.assertFalse(output.exists())
                    self.assertEqual(repair.main(["--snapshot", str(snapshot), "--sql-output", str(output)]), 0)
                    original = output.read_bytes()
                    self.assertEqual(repair.main(["--snapshot", str(snapshot), "--sql-output", str(output)]), 2)
                    self.assertEqual(output.read_bytes(), original)

    def test_invalid_snapshot_does_not_create_sql(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            snapshot = root / "snapshot.json"
            data = demo_snapshot()
            data[-1]["items"][0]["quantity"] = 99
            snapshot.write_text(json.dumps(data), encoding="utf-8")
            output = root / "repair.sql"
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                self.assertEqual(repair.main(["--snapshot", str(snapshot), "--sql-output", str(output)]), 2)
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
