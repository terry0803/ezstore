"""Attested Computation 的 executor 與驗證。

executor 照知識庫的 references/skills/run-python-computation.md：抓資料來源、綁參數、
執行條目指定的計算程式，回傳收據。數字要先交給條目的 attester 驗證，通過才可以顯示。
"""

from __future__ import annotations

import hashlib
import json
import types
from typing import Any

from .backend import Backend, BackendError
from .okf import Bundle, Concept, OKFError, format_time, utc_now

PRICE_CHANGE_IMPACT = "computations/price-change-impact"

_TYPES: dict[str, tuple[type, ...]] = {"string": (str,), "number": (int, float), "integer": (int,)}


class ComputationError(RuntimeError):
    """參數不對、資料抓不到、計算程式和登記版本不同。"""


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_json(data: Any) -> bytes:
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _load_function(path, name: str):
    """載入知識庫裡的程式檔。直接 compile，不在知識庫裡留下 __pycache__。"""
    source = path.read_bytes()
    module = types.ModuleType(f"okf_{path.stem}_{sha256_hex(source)[:12]}")
    module.__file__ = str(path)
    exec(compile(source, str(path), "exec"), module.__dict__)
    return getattr(module, name)


def computation_concept(bundle: Bundle, concept_id: str = PRICE_CHANGE_IMPACT) -> Concept:
    concept = bundle.get(concept_id)
    if concept is None or concept.type != "Attested Computation":
        raise ComputationError(f"知識庫沒有 {concept_id} 這個 Attested Computation")
    if concept.frontmatter.get("runtime") != "python":
        raise ComputationError(f"{concept_id} 的 runtime 不是 python")
    if concept.is_deprecated():
        raise ComputationError(f"{concept_id} 已作廢，不執行")
    return concept


def _pinned_file(bundle: Bundle, concept: Concept, path_value: Any, pin_key: str, label: str):
    """知識庫裡的程式要和條目登記的 sha256 一樣才可以載入；沒登記也不載入。"""
    if not path_value:
        raise ComputationError(f"條目沒有寫{label}的位置，不執行")
    pinned = concept.frontmatter.get(pin_key)
    if not pinned:
        raise ComputationError(f"{label}沒有登記 {pin_key}，不執行")
    try:
        path = bundle.resolve_path(str(path_value), concept)
        actual = sha256_hex(path.read_bytes())
    except (OSError, OKFError) as e:
        raise ComputationError(f"讀不到{label}：{e}") from e
    if actual != pinned:
        raise ComputationError(f"{label}和知識庫登記的 {pin_key} 不同，不執行")
    return path, actual


def _check_parameters(concept: Concept, params: dict[str, Any]) -> None:
    declared = {p["name"]: p for p in concept.frontmatter.get("parameters") or []}
    for name, spec in declared.items():
        if spec.get("required") and params.get(name) is None:
            raise ComputationError(f"缺少參數 {name}")
    for name, value in params.items():
        if name not in declared:
            raise ComputationError(f"條目沒有宣告參數 {name}")
        expected = _TYPES.get(declared[name].get("type") or "")
        if expected and (isinstance(value, bool) or not isinstance(value, expected)):
            raise ComputationError(f"參數 {name} 要是 {declared[name].get('type')}")


async def run_price_change_impact(
    bundle: Bundle, backend: Backend, quotation_number: str, target_total: float
) -> dict[str, Any]:
    """執行改價影響試算，回傳收據（欄位依條目的 executor.receipt）。"""
    concept = computation_concept(bundle)
    fm = concept.frontmatter
    params = {"quotation_number": quotation_number, "target_total": target_total}
    _check_parameters(concept, params)

    # 程式被改過、或沒有登記版本，就不執行
    computation_file, code_sha = _pinned_file(bundle, concept, fm["computation"], "computation_sha256", "計算程式")

    try:
        source = await backend.find_quotation(quotation_number)
    except BackendError as e:
        raise ComputationError(f"讀不到報價單：{e}") from e
    if source is None:
        raise ComputationError(f"找不到報價單 {quotation_number}")

    selector = fm.get("source_parameter")
    arguments = {k: v for k, v in params.items() if k != selector}
    try:
        result = _load_function(computation_file, "compute")(source, **arguments)
    except (ValueError, KeyError, ArithmeticError) as e:
        raise ComputationError(f"試算失敗：{e}") from e

    receipt = {
        "computation": fm["computation"],
        "computation_sha256": code_sha,
        "source_url": backend.url(f"/quotations/{source['id']}"),
        "source_sha256": sha256_hex(canonical_json(source)),
        "source": source,
        "parameters": params,
        "result": result,
        "executed_at": format_time(utc_now()),
    }
    fields = (fm.get("executor") or {}).get("receipt") or list(receipt)
    return {k: receipt[k] for k in fields if k in receipt}


def attest_receipt(bundle: Bundle, receipt: dict[str, Any], claimed: dict[str, Any] | None = None) -> dict[str, Any]:
    """交給條目指定的 attester（確定性的程式，不用 LLM）。attester 一樣要符合登記的 sha256。"""
    try:
        concept = computation_concept(bundle)
        attester_file, _ = _pinned_file(
            bundle, concept, (concept.frontmatter.get("attester") or {}).get("resource"), "attester_sha256", "驗證程式（attester）"
        )
    except ComputationError as e:
        return {"ok": False, "reason": str(e), "details": {}}
    try:
        attest = _load_function(attester_file, "attest")
        return attest(bundle_root=bundle.root, concept=concept.frontmatter, receipt=receipt, claimed=claimed)
    except Exception as e:  # attester 本身出錯也當成驗證失敗
        return {"ok": False, "reason": f"attester 執行失敗：{e.__class__.__name__}", "details": {}}


def stale_note(bundle: Bundle, now=None) -> str | None:
    """試算條目過期時回傳提醒文字（規格 §10.5：過期要警告或拒絕）。"""
    concept = computation_concept(bundle)
    if concept.is_stale(now or utc_now()):
        return f"試算條目 {concept.id} 已過期（stale_after {format_time(concept.stale_after())}），要人重新審核"
    return None
