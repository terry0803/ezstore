"""依 OKF 知識庫裡的規則條目判斷改價與轉訂單。

規則條目是 type: Policy、帶 rule_kind 的條目，判斷用的數字都寫在 frontmatter：

- margin_tiers：依改價後毛利率決定核准層級
- factor_floor：各客戶等級的報價因子下限
- factor_floor_override：暫時覆蓋某個等級的下限（例如季度促銷）
- order_conversion：轉訂單的條件

已作廢（status: deprecated）與已過期（now >= stale_after）的條目不拿來判斷，
會列在 skipped 讓回覆說明。多條規則同時適用時取最嚴的層級。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any

from .okf import Bundle, Concept, format_date_tw, utc_now

APPROVAL_ORDER = ("none", "sales_manager", "general_manager", "forbidden")
APPROVAL_LABELS = {
    "none": "業務可直接調整",
    "sales_manager": "需業務主管核准",
    "general_manager": "需總經理核准",
    "forbidden": "不可報價",
}


def stricter(a: str, b: str) -> str:
    return a if APPROVAL_ORDER.index(a) >= APPROVAL_ORDER.index(b) else b


@dataclass
class RuleVerdict:
    concept_id: str
    title: str
    approval: str
    reason: str
    trust: str

    @property
    def label(self) -> str:
        return APPROVAL_LABELS[self.approval]


@dataclass
class PriceDecision:
    approval: str
    verdicts: list[RuleVerdict] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)  # (條目 id, 原因)

    @property
    def label(self) -> str:
        return APPROVAL_LABELS[self.approval]

    @property
    def can_apply(self) -> bool:
        return self.approval == "none"


@dataclass
class OrderDecision:
    allowed: bool
    reasons: list[str] = field(default_factory=list)
    rules: list[RuleVerdict] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)
    existing_orders: list[str] = field(default_factory=list)


def _usable(concept: Concept, now: datetime) -> str | None:
    """不能用的原因；可以用時回 None。"""
    if concept.is_deprecated():
        return "已作廢"
    if concept.is_stale(now):
        return f"{format_date_tw(concept.stale_after())} 起過期"
    return None


def _percent(value: Decimal) -> str:
    return f"{(value * 100).quantize(Decimal('0.01'))}%"


# 改價必須同時有這兩類規則可用，少了任何一類就不放行
REQUIRED_RULES = {"margin_tiers": "改價核准層級", "factor_floor": "報價因子下限"}


def _approval(value: Any) -> str:
    """規則裡寫的核准層級；寫錯的當成不可報價，修好之前不能靠它放行。"""
    return value if value in APPROVAL_ORDER else "forbidden"


def _tier_of(margin: Decimal, tiers: list, below: str) -> str:
    for tier in tiers:
        if margin >= Decimal(str(tier["min_margin"])):
            return _approval(tier.get("approval"))
    return below


def gate_numbers(result: dict[str, Any], conservative: bool = True) -> tuple[Decimal, Decimal, Decimal]:
    """寫入前用已驗證的 MCP 二分法結果；寫入後核對實際值，毛利率不先捨入。"""
    cost_total = Decimal(result["cost_total"])
    factor = Decimal(result["new_factor"] if conservative else result["current_factor"])
    low_factor = factor
    total = Decimal(result["new_total"] if conservative else result["current_total"])
    margin = (total - cost_total) / total if total else Decimal(-1)
    return margin, low_factor, factor


def evaluate_price_change(
    bundle: Bundle, result: dict[str, Any], now: datetime | None = None, conservative: bool = True
) -> PriceDecision:
    """result 是改價影響試算（已通過 attester）的結果。"""
    now = now or utc_now()
    decision = PriceDecision(approval="none")
    shown_margin = Decimal(result["new_margin"] if conservative else result["current_margin"])
    margin, low_factor, factor = gate_numbers(result, conservative)
    level = str(result.get("customer_level") or "")
    usable: set[str] = set()

    for concept in sorted(bundle.find(type_name="Policy", rule_kind="margin_tiers"), key=lambda c: c.id):
        reason = _usable(concept, now)
        if reason:
            decision.skipped.append((concept.id, reason))
            continue
        fm = concept.frontmatter
        try:
            tiers = sorted(fm.get("margin_tiers") or [], key=lambda t: Decimal(str(t["min_margin"])), reverse=True)
            below = _approval((fm.get("below_lowest") or {}).get("approval", "forbidden"))
            approval = _tier_of(margin, tiers, below)
            shown = _tier_of(shown_margin, tiers, below)
        except (KeyError, TypeError, ArithmeticError):
            decision.verdicts.append(
                RuleVerdict(concept.id, concept.title, "forbidden", "規則格式錯誤，修好之前不能用來放行", concept.trust_note(now))
            )
            continue
        text = f"改價後毛利率 {_percent(shown_margin)}"
        if approval != shown:
            exact = f"{(margin * 100).quantize(Decimal('0.0001'))}%"
            text += f"（以二分法結果未捨入毛利率 {exact} 判斷）" if conservative else f"（不四捨五入是 {exact}）"
        decision.verdicts.append(RuleVerdict(concept.id, concept.title, approval, text, concept.trust_note(now)))
        usable.add("margin_tiers")

    overrides: dict[str, tuple[Decimal, Concept]] = {}
    for concept in sorted(bundle.find(type_name="Policy", rule_kind="factor_floor_override"), key=lambda c: c.id):
        reason = _usable(concept, now)
        if reason:
            decision.skipped.append((concept.id, reason))
            continue
        fm = concept.frontmatter
        try:
            overrides[str(fm.get("applies_to_level"))] = (Decimal(str(fm["factor_floor"])), concept)
        except (KeyError, TypeError, ArithmeticError):
            decision.skipped.append((concept.id, "規則格式錯誤"))

    for concept in sorted(bundle.find(type_name="Policy", rule_kind="factor_floor"), key=lambda c: c.id):
        reason = _usable(concept, now)
        if reason:
            decision.skipped.append((concept.id, reason))
            continue
        fm = concept.frontmatter
        floors = fm.get("factor_floor") or {}
        usable.add("factor_floor")
        if level not in floors:
            decision.verdicts.append(
                RuleVerdict(concept.id, concept.title, "sales_manager", f"客戶等級「{level}」不在下限表裡", concept.trust_note(now))
            )
            continue
        try:
            floor = Decimal(str(floors[level]))
        except ArithmeticError:
            decision.verdicts.append(
                RuleVerdict(concept.id, concept.title, "forbidden", "規則格式錯誤，修好之前不能用來放行", concept.trust_note(now))
            )
            continue
        source = ""
        if level in overrides:
            floor, override = overrides[level]
            source = f"（依 {override.id} 暫時改為 {floor:.2f}）"
        if low_factor < floor:
            approval = _approval((fm.get("below_floor") or {}).get("approval", "sales_manager"))
            text = f"報價因子 {factor} 低於 {level} 的下限 {floor:.2f}{source}"
        else:
            approval = "none"
            text = f"報價因子 {factor} 沒有低於 {level} 的下限 {floor:.2f}{source}"
        decision.verdicts.append(RuleVerdict(concept.id, concept.title, approval, text, concept.trust_note(now)))

    for kind, label in REQUIRED_RULES.items():
        if kind not in usable:
            decision.verdicts.append(
                RuleVerdict(
                    f"missing:{kind}", f"缺少{label}", "sales_manager",
                    "知識庫沒有可用的這類規則（作廢、過期或不存在），保守起見要主管核准", "—",
                )
            )

    for verdict in decision.verdicts:
        decision.approval = stricter(decision.approval, verdict.approval)
    return decision


def evaluate_order_conversion(
    bundle: Bundle, quotation: dict[str, Any], orders: list[dict[str, Any]], now: datetime | None = None
) -> OrderDecision:
    """quotation 是後端的報價單 JSON；orders 是同一個客戶的訂單清單。"""
    now = now or utc_now()
    decision = OrderDecision(allowed=True)
    concepts = sorted(bundle.find(type_name="Policy", rule_kind="order_conversion"), key=lambda c: c.id)
    usable = []
    for concept in concepts:
        reason = _usable(concept, now)
        if reason:
            decision.skipped.append((concept.id, reason))
        else:
            usable.append(concept)
    if not usable:
        decision.allowed = False
        decision.reasons.append("知識庫沒有可用的轉訂單規則，不經 Agent 轉訂單")
        return decision

    for concept in usable:
        fm = concept.frontmatter
        ok = True
        required = fm.get("require_status")
        if required and quotation.get("status") != required:
            ok = False
            decision.reasons.append(f"報價單狀態是 {quotation.get('status')}，要 {required} 才可以轉訂單")
        if fm.get("block_if_existing_order"):
            ignored = set(fm.get("ignore_order_status") or [])
            for order in orders:
                if order.get("quotation_id") == quotation.get("id") and order.get("status") not in ignored:
                    decision.existing_orders.append(f"{order.get('order_number')}（{order.get('status')}）")
            if decision.existing_orders:
                ok = False
                decision.reasons.append("這張報價單已經有訂單：" + "、".join(decision.existing_orders))
        decision.rules.append(
            RuleVerdict(concept.id, concept.title, "none" if ok else "forbidden", "符合" if ok else "不符合", concept.trust_note(now))
        )
        decision.allowed = decision.allowed and ok
    return decision
