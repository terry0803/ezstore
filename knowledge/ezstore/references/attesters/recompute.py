"""runtime: python 的 Attested Computation 用的 attester。

只做確定性的比對：不用 LLM、不連網路，在使用知識的那一端（Agent）執行。

attest() 的輸入：
  bundle_root  知識庫根目錄
  concept      計算條目的 frontmatter（dict）
  receipt      executor 回傳的收據
  claimed      準備顯示給使用者的數字，key 同收據的 result

依序檢查，第一個不符就回傳失敗：
  1. 計算程式：知識庫裡 computation 檔案的 sha256，要等於條目登記的 computation_sha256，
     也要等於收據的 computation_sha256（執行的就是知識庫指定的那一份）
  2. 參數：收據的參數名稱與型別符合條目宣告
  3. 資料來源：收據附的來源資料重算 sha256，要等於收據的 source_sha256；
     來源資料要對應 source_parameter 指定的那個值
  4. 結果：用知識庫的計算程式重算一次，要和收據的 result 完全相同
  5. 顯示：claimed 的每個值都要等於收據的 result

回傳 {"ok": bool, "reason": str | None, "details": {...}}。
"""

from __future__ import annotations

import hashlib
import json
import types
from pathlib import Path
from typing import Any

_TYPES: dict[str, tuple[type, ...]] = {
    "string": (str,),
    "number": (int, float),
    "integer": (int,),
    "boolean": (bool,),
}


def canonical_json(data: Any) -> bytes:
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def resolve_bundle_path(bundle_root: Path, path: str) -> Path:
    """條目裡以 / 開頭的路徑是相對於知識庫根目錄；不允許跑出知識庫。"""
    root = Path(bundle_root).resolve()
    target = (root / path.lstrip("/")).resolve()
    if root != target and root not in target.parents:
        raise ValueError(f"路徑跑出知識庫：{path}")
    return target


def load_compute(file: Path):
    """直接 compile 計算程式，不在知識庫裡留下 __pycache__。"""
    source = file.read_bytes()
    module = types.ModuleType(f"okf_computation_{sha256_hex(source)[:12]}")
    module.__file__ = str(file)
    exec(compile(source, str(file), "exec"), module.__dict__)
    return module.compute


def _type_ok(value: Any, type_name: str | None) -> bool:
    expected = _TYPES.get(type_name or "")
    if expected is None:
        return True
    if isinstance(value, bool) and bool not in expected:
        return False
    return isinstance(value, expected)


def attest(*, bundle_root: Path, concept: dict, receipt: dict, claimed: dict | None = None) -> dict:
    details: dict[str, Any] = {}

    def fail(reason: str) -> dict:
        return {"ok": False, "reason": reason, "details": details}

    # 1. 計算程式
    computation_file = resolve_bundle_path(Path(bundle_root), concept["computation"])
    actual = sha256_hex(computation_file.read_bytes())
    details["computation_sha256"] = actual
    pinned = concept.get("computation_sha256")
    if pinned and pinned != actual:
        return fail("知識庫裡的計算程式被改過，和條目登記的 computation_sha256 不同")
    if receipt.get("computation_sha256") != actual:
        return fail("收據裡執行的不是條目指定的計算程式")

    # 2. 參數
    params = receipt.get("parameters") or {}
    declared = {p["name"]: p for p in concept.get("parameters") or []}
    for name, spec in declared.items():
        if spec.get("required") and name not in params:
            return fail(f"缺少參數 {name}")
    for name, value in params.items():
        if name not in declared:
            return fail(f"收據帶了條目沒宣告的參數 {name}")
        if not _type_ok(value, declared[name].get("type")):
            return fail(f"參數 {name} 的型別不是 {declared[name].get('type')}")

    # 3. 資料來源
    source = receipt.get("source")
    if source is None or sha256_hex(canonical_json(source)) != receipt.get("source_sha256"):
        return fail("來源資料和收據的 source_sha256 不同")
    selector = concept.get("source_parameter")
    if selector and source.get(selector) != params.get(selector):
        return fail(f"來源資料不是參數 {selector} 指定的那一筆")

    # 4. 結果
    compute = load_compute(computation_file)
    arguments = {k: v for k, v in params.items() if k != selector}
    recomputed = compute(source, **arguments)
    if recomputed != receipt.get("result"):
        details["recomputed"] = recomputed
        return fail("用知識庫的計算程式重算，結果和收據不同")

    # 5. 顯示
    for key, value in (claimed or {}).items():
        if recomputed.get(key) != value:
            return fail(f"準備顯示的 {key} 和收據不同")

    return {"ok": True, "reason": None, "details": details}
