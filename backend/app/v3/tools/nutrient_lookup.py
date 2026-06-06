"""Nutrient Lookup — 식약처 영양소 API 래퍼.

Sprint 1: mock 영양소 (FRIDGEMATE_MOCK_MODE=true 시).
Sprint 2: 식약처 API 실제 호출 + respx 모킹.
"""
from __future__ import annotations

# 100g당 영양소 (mock — Sprint 2 식약처 API 교체)
MOCK_NUTRIENT_DB: dict[str, dict[str, float]] = {
    "닭가슴살": {"kcal": 165, "protein": 31, "carb": 0, "fat": 3.6, "fiber": 0},
    "계란": {"kcal": 155, "protein": 13, "carb": 1.1, "fat": 11, "fiber": 0},
    "브로콜리": {"kcal": 34, "protein": 2.8, "carb": 7, "fat": 0.4, "fiber": 2.6},
    "양파": {"kcal": 40, "protein": 1.1, "carb": 9.3, "fat": 0.1, "fiber": 1.7},
    "마늘": {"kcal": 149, "protein": 6.4, "carb": 33, "fat": 0.5, "fiber": 2.1},
    "쌀": {"kcal": 130, "protein": 2.7, "carb": 28, "fat": 0.3, "fiber": 0.4},
    "고구마": {"kcal": 86, "protein": 1.6, "carb": 20, "fat": 0.1, "fiber": 3.0},
    "두부": {"kcal": 76, "protein": 8, "carb": 1.9, "fat": 4.8, "fiber": 0.3},
}

DEFAULT_NUTRIENT = {"kcal": 100, "protein": 5, "carb": 15, "fat": 3, "fiber": 1}


def nutrient_lookup_mock(item_name: str) -> dict[str, float]:
    return MOCK_NUTRIENT_DB.get(item_name, DEFAULT_NUTRIENT).copy()


async def nutrient_lookup(item_name: str) -> dict[str, float]:
    """Sprint 2에서 식약처 API 호출로 교체."""
    return nutrient_lookup_mock(item_name)
