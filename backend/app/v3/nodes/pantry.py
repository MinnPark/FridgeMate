"""Pantry 노드 — v3 진입점. 냉장고 재고를 구조화 + 영양소 부여.

v3 흐름의 두 번째 노드 (orchestrator → **pantry** → intake → meal_plan_composer → ...).
사용자가 입력한 fridge_items (자연어 리스트) → 표준 {name, qty, unit, nutrients, priority} 리스트.

⚠️ 영양소는 현재 nutrient_lookup_mock — 식약처 영양 API 미연결 (sprint_status #5 참조).
"""
from __future__ import annotations

from app.v3.state import FridgeMateState
from app.v3.tools.ingredient_parser import parse_ingredients
from app.v3.tools.nutrient_lookup import nutrient_lookup_mock


async def pantry_node(state: FridgeMateState) -> dict:
    raw_items = state.get("fridge_items", [])
    parsed = parse_ingredients(raw_items)

    pantry = []
    for item in parsed:
        nutrients = nutrient_lookup_mock(item["name"])
        pantry.append({
            **item,
            "nutrients": nutrients,
            "priority": 2,  # Sprint 2: expiry_checker 연결
        })

    return {"pantry": pantry}
