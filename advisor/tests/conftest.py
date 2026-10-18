"""共用的測試資料：知識庫路徑、測試資料快照（重灌 seed 後從後端 API 取的）、假的後端。"""

import json
import os
import shutil
import socket
import sys
from pathlib import Path

import pytest
from pricing_advisor.backend import Backend

os.environ["PYTHON_DOTENV_DISABLED"] = "1"
os.environ.setdefault("AGENT_MODEL", "gemini-3.8-flash")

ROOT = Path(__file__).resolve().parents[2]
BUNDLE = ROOT / "knowledge" / "ezstore"
SNAPSHOT = json.loads((Path(__file__).parent / "fixtures" / "seed_snapshot.json").read_text(encoding="utf-8"))


class FakeBackend(Backend):
    """只回測試資料快照，不連網路。"""

    base_url = "http://backend:8080/api/v1"

    def __init__(self, quotations=None, orders=None):
        self.quotations = quotations if quotations is not None else SNAPSHOT["quotations"]
        self.orders = orders if orders is not None else SNAPSHOT["orders_by_customer"]
        self.products = {i['product_id']: {'cost': i['product_cost'], 'list_price': i['list_price']}
                         for q in SNAPSHOT['quotations'].values() for i in q['items']}

    async def _get(self, path, **params):
        assert path.startswith('/products/')
        return self.products[int(path.rsplit('/', 1)[1])]

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
def isolated_conversion_state(monkeypatch):
    from pricing_advisor import agent
    monkeypatch.setattr(agent, '_CONVERT_UNCERTAIN', {})
    monkeypatch.setattr(agent, '_CONVERT_LOCKS', {})


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """所有既有測試皆使用假後端／模型，意外外連立即失敗而非消耗 API 額度。"""
    def blocked(*args, **kwargs):
        raise AssertionError("Offline tests must not open network connections")

    original_connect = socket.socket.connect

    def guarded_connect(sock, address):
        # Windows asyncio 用標準庫 socketpair 的 loopback 連線建立內部喚醒管道。
        # 僅放行該函式自身的 connect；模型、HTTP 與測試程式的連線仍一律拒絕。
        pair_code = getattr(socket.socketpair, "__code__", None)
        if pair_code is not None and sys._getframe(1).f_code is pair_code:
            return original_connect(sock, address)
        return blocked()

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)
    monkeypatch.setattr(socket, "getaddrinfo", blocked)


@pytest.fixture(autouse=True)
def fixed_now(monkeypatch):
    # 固定「現在」：Q3 促銷已過期、其他條目都還沒過期
    monkeypatch.setenv("OKF_NOW", "2026-10-17T02:00:00Z")
