"""金額解析：從報價單 Agent（agent/quotation_agent/agent.py）搬過來的同一套規則。

兩個 Agent 是分開的套件，不能互相 import，所以複製一份；改其中一邊時另一邊也要改。
「18萬5」「一萬二」「二百五」這類有兩種讀法的寫法回 None，交給呼叫端追問。
"""

from __future__ import annotations

import math
import re
from typing import Any

_NUMERIC_CHARS = "零〇一壹二兩貳三參四肆五伍六陸七柒八捌九玖十拾百佰千仟萬万億亿點点"


def clean_number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def chinese_number(text: str) -> float | None:
    """Parse explicit Chinese place values; ambiguous shorthand is not guessed."""
    sign = -1 if text.startswith(("-", "負", "负")) else 1
    text = text.lstrip("+-負负")
    digits = {c: n for n, chars in enumerate(("零〇", "一壹", "二兩貳", "三參", "四肆", "五伍", "六陸", "七柒", "八捌", "九玖")) for c in chars}
    units = {"十": 10, "拾": 10, "百": 100, "佰": 100, "千": 1000, "仟": 1000}
    large = {"萬": 10000, "万": 10000, "億": 100000000, "亿": 100000000}
    multiplier = 1
    if any(dot in text for dot in ("點", "点")) and text[-1:] in {**units, **large}:
        multiplier = {**units, **large}[text[-1]]
        text = text[:-1]
    integer, dot, fraction = text.replace("點", ".").replace("点", ".").partition(".")
    if not integer or (dot and (not fraction or any(c not in digits for c in fraction))):
        return None
    if all(c in digits for c in integer):
        value = float("".join(str(digits[c]) for c in integer))
    else:
        total = section = current = 0
        small_limit, large_limit, last_unit = 10000, 10**12, 1
        zero_after_unit = False
        for char in integer:
            if char in digits:
                if current and digits[char]:
                    return None
                current = digits[char]
                zero_after_unit = zero_after_unit or current == 0
            elif char in units:
                unit = units[char]
                if unit >= small_limit:
                    return None
                section += (current or 1) * unit
                current, small_limit, last_unit, zero_after_unit = 0, unit, unit, False
            elif char in large:
                unit = large[char]
                if unit >= large_limit or section + current == 0:
                    return None
                total += (section + current) * unit
                section, current, small_limit = 0, 0, 10000
                large_limit, last_unit, zero_after_unit = unit, unit, False
            else:
                return None
        # 一萬二/二百五 can mean different amounts. Require 二千/零二 etc.
        if current and last_unit >= 100 and not zero_after_unit:
            return None
        value = float(total + section + current)
    if dot:
        value += float("0." + "".join(str(digits[c]) for c in fraction))
    return clean_number(sign * value * multiplier)


def parse_number_token(token: str) -> float | None:
    token = token.strip().rstrip(",")
    if not token or len(token) > 128:
        return None
    if not re.search(r"\d", token):
        return chinese_number(token)
    sign = -1 if token.startswith(("-", "負", "负")) else 1
    token = token.lstrip("+-負负")
    scalar = r"(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?:[eE][-+]?\d+)?"
    scales = {"百": 100, "佰": 100, "千": 1000, "仟": 1000, "萬": 10000, "万": 10000, "億": 100000000, "亿": 100000000}
    pieces = list(re.finditer(rf"({scalar})([百佰千仟萬万億亿]?)", token))
    if not pieces or "".join(match.group(0) for match in pieces) != token:
        return None
    result, previous_scale = 0.0, float("inf")
    for match in pieces:
        unit = match.group(2)
        scale = scales.get(unit, 1)
        # 18萬5 is ambiguous; 18萬5千 is explicit. Unit order must decrease.
        if scale >= previous_scale or (not unit and len(pieces) > 1):
            return None
        value = clean_number(match.group(1).replace(",", ""))
        if value is None:
            return None
        result += value * scale
        previous_scale = scale
    return clean_number(sign * result)
