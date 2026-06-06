"""Ingredient Parser — 자연어 재료 → 구조화 dict.

"닭가슴살 200g" → {"name": "닭가슴살", "qty": 200, "unit": "g", "raw_text": "..."}
Sprint 1: 정규식 기반. Sprint 2+: LLM fallback parser 추가 (R12 대응).
"""
from __future__ import annotations

import re

UNIT_PATTERN = re.compile(
    r"^(?P<name>[가-힣A-Za-z]+(?:\s[가-힣A-Za-z]+)?)"
    r"\s*"
    r"(?:(?P<qty>\d+(?:\.\d+)?)\s*(?P<unit>g|kg|ml|l|개|마리|봉|팩|컵|큰술|작은술|모|장|쪽))?",
    re.UNICODE,
)


def parse_ingredient(raw: str) -> dict:
    text = raw.strip()
    match = UNIT_PATTERN.search(text)
    if not match or not match.group("name"):
        return {"name": text, "qty": None, "unit": None, "raw_text": raw}

    name = match.group("name").strip()
    qty = match.group("qty")
    unit = match.group("unit")
    return {
        "name": name,
        "qty": float(qty) if qty else None,
        "unit": unit,
        "raw_text": raw,
    }


def parse_ingredients(raw_items: list[str]) -> list[dict]:
    return [parse_ingredient(item) for item in raw_items if item and item.strip()]
