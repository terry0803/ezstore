"""共用的測試資料：知識庫路徑、測試資料快照（重灌 seed 後從後端 API 取的）、假的後端。"""

import json
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BUNDLE = ROOT / "knowledge" / "ezstore"
SNAPSHOT = json.loads((Path(__file__).parent / "fixtures" / "seed_snapshot.json").read_text(encoding="utf-8"))


class FakeBackend:
    """只回測試資料快照，不連網路。"""

    base_url = "http://backend:8080/api/v1"

    def __init__(self, quotations=None, orders=None):
        self.quotations = quotations if quotations is not None else SNAPSHOT["quotations"]
        self.orders = orders if orders is not None else SNAPSHOT["orders_by_customer"]

    def url(self, path):
        return f"{self.base_url}{path}"

    async def find_quotation(self, number):
        found = self.quotations.get(number)
        return json.loads(json.dumps(found)) if found else None

    async def customer_orders(self, customer_id):
        return list(self.orders.get(str(customer_id), []))


@pytest.fixture
def bundle_path():
    return BUNDLE


@pytest.fixture
def bundle_copy(tmp_path):
    """可以改的知識庫副本。"""
    target = tmp_path / "bundle"
    shutil.copytree(BUNDLE, target, ignore=shutil.ignore_patterns("viz.html", "__pycache__"))
    return target


@pytest.fixture
def fake_backend():
    return FakeBackend()


@pytest.fixture
def snapshot():
    return SNAPSHOT


@pytest.fixture(autouse=True)
def fixed_now(monkeypatch):
    # 固定「現在」：Q3 促銷已過期、其他條目都還沒過期
    monkeypatch.setenv("OKF_NOW", "2026-10-17T02:00:00Z")
