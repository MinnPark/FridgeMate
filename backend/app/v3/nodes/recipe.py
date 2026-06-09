"""Recipe 노드 — v3. meal_plan 의 각 끼니 슬롯에 풀 레시피 매칭.

meal_plan_composer 가 배치한 식단(MealSlot)을 받아 각 슬롯 요리의 풀 레시피를 로드한다.
recipe_id 있으면 시드/DB 직접 로드, 없으면(사용자 직접 추가 슬롯) dish_resolver 로 매칭.
모든 레시피에 citation 필수 (없으면 KPI citation_included=False).

Sprint(후속): HyDE / RAG-Fusion + user_preference boost + LLM 커스터마이징.
"""
from __future__ import annotations

import json
from pathlib import Path

from app.v3.state import FridgeMateState
from app.v3.tools.dish_resolver import resolve_dish

SEED_PATH = Path(__file__).resolve().parents[1] / "data" / "seed_recipes.json"


def _load_seed_index() -> dict[str, dict]:
    raw = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    return {r["id"]: r for r in raw}


_SEED_INDEX = _load_seed_index()


def _recipe_from_seed(r: dict, slot: dict) -> dict:
    return {
        "dish_name": r["name"],
        "day": slot.get("day", ""),
        "meal_type": slot.get("meal_type", ""),
        "ingredients": r.get("ingredients") or [],
        "steps": r.get("steps") or [],
        "time_min": int(r.get("time_min", 30)),
        "cuisine_type": r.get("cuisine_type", "기타"),
        "calories": r.get("calories", 0),
        "protein": r.get("protein", 0),
        "carb": r.get("carb", 0),
        "fat": r.get("fat", 0),
        "citation": {
            "source": "recipe_db (seed)",
            "url": r.get("source_url", ""),
            "id": r["id"],
        },
        "resolved": True,
        "match_distance": None,
    }


async def recipe_node(state: FridgeMateState) -> dict:
    constraints = state.get("constraints") or {}
    max_time = constraints.get("max_time")
    meal_plan = state.get("meal_plan") or []

    if not meal_plan:
        return {
            "recipes": [],
            "errors": ["meal_plan 비어 있음 — meal_plan_composer 단계 확인"],
        }

    recipes: list[dict] = []
    for slot in meal_plan:
        recipe_id = slot.get("recipe_id")
        name = slot.get("dish_name") or ""

        # composer 가 동봉한 풀 레시피가 있으면 그대로 사용 — 같은 레시피를 RAG 로 두 번
        # 검색하던 낭비(슬롯당 HyDE 호출)를 제거한다. (seed/RAG 후보 동일 스키마)
        embedded = slot.get("recipe")
        if embedded and embedded.get("name"):
            recipes.append(_recipe_from_seed(embedded, slot))
            continue

        if recipe_id and recipe_id in _SEED_INDEX:
            recipes.append(_recipe_from_seed(_SEED_INDEX[recipe_id], slot))
            continue

        resolved = await resolve_dish(name, max_time=max_time)
        recipes.append({
            "dish_name": resolved["name"],
            "day": slot.get("day", ""),
            "meal_type": slot.get("meal_type", ""),
            "ingredients": resolved["ingredients"],
            "steps": resolved["steps"],
            "time_min": resolved.get("time_min", 30),
            "cuisine_type": resolved.get("cuisine_type", "기타"),
            "calories": resolved.get("calories", 0),
            "protein": resolved.get("protein", 0),
            "carb": resolved.get("carb", 0),
            "fat": resolved.get("fat", 0),
            "citation": {
                "source": "recipe_db (resolver)",
                "url": resolved.get("source_url") or "",
                "id": resolved.get("id"),
            },
            "resolved": resolved.get("resolved", False),
            "match_distance": resolved.get("match_distance"),
        })

    citation_ok = all(r.get("citation", {}).get("id") for r in recipes)
    return {
        "recipes": recipes,
        "kpi_log": {
            **(state.get("kpi_log") or {}),
            "citation_included": citation_ok,
        },
    }
