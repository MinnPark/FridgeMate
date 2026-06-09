"""Meal Plan Composer 노드 — v3 핵심 신규.

냉장고 재고 × 선호도 × 영양 목표 × 라이프스타일 패턴 → recipe_db 안에서 식단 구성.
끼니별 슬롯에 요리를 배치한다. 요리 단건이 아니라 식단(meal_plan) 단위.

"개밥 방지": 후보는 반드시 recipe_db(seed) 검증 레시피 안. 재고 임의 조합 X.
"냉장고 우선": pantry_coverage 가 강한 가중치.
locked_dishes 의 요리는 reflexion 재구성 시에도 슬롯에 보존된다.

Sprint(후속): seed 순회 → ChromaDB 전체 인덱스 + Cohere 임베딩 매칭으로 교체.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from app.v3.state import FridgeMateState

SEED_RECIPES_PATH = Path(__file__).resolve().parents[1] / "data" / "seed_recipes.json"

WEIGHTS = {
    "pantry":   float(os.getenv("W_PANTRY", "0.35")),
    "pref":     float(os.getenv("W_PREF", "0.25")),
    "nutri":    float(os.getenv("W_NUTRI", "0.25")),
    "goal":     float(os.getenv("W_GOAL", "0.15")),
}
NUTRIENT_WEIGHTS = {"kcal": 0.3, "protein": 0.4, "carb": 0.15, "fat": 0.15}


def _load_seed_recipes() -> list[dict]:
    return json.loads(SEED_RECIPES_PATH.read_text(encoding="utf-8"))


async def _get_rag_candidates(
    *,
    intake_text: str,
    dish_goals: list[str],
    prefs: dict,
    constraints: dict,
    k: int,
) -> list[dict]:
    """RAG(`smart_search`) 로 레시피 후보 풀 구성.

    신호 우선순위: dish_goals → intake_text → preferences.favorites/cuisines.
    각 쿼리당 top-N 을 모아 dedup → 최대 k 건. ChromaDB 비었거나 실패 시 [] (composer 가 seed fallback).
    """
    try:
        from app.rag.smart_search import smart_search
    except Exception:
        return []

    max_time = (constraints or {}).get("max_time")
    candidates: dict[str, dict] = {}

    queries: list[str] = list(dish_goals or [])
    if intake_text:
        queries.append(intake_text)
    queries.extend((prefs or {}).get("favorites") or [])
    queries.extend((prefs or {}).get("cuisines") or [])
    if not queries:
        # 신호 0 → 광범위 토큰으로 폭넓게 가져오기 (seed 인덱스라도 다양성 확보)
        queries = ["요리", "한식"]

    for q in queries:
        if len(candidates) >= k:
            break
        try:
            results = await smart_search(q, k=min(10, k), max_time=max_time)
        except Exception:
            continue
        for r in results:
            rid = r.get("id")
            if rid and rid not in candidates:
                candidates[rid] = r

    return list(candidates.values())[:k]


def _build_slots(schedule: dict, dish_goals: list[str]) -> list[dict]:
    """schedule.days × schedule.meals = 끼니 슬롯. 없으면 dish_goals 수(최소 1)만큼 단일 끼니."""
    days = schedule.get("days") or []
    meals = schedule.get("meals") or []
    if days and meals:
        return [{"day": d, "meal_type": m} for d in days for m in meals]
    if days:
        return [{"day": d, "meal_type": "저녁"} for d in days]
    count = max(len(dish_goals), 1)
    return [{"day": "오늘", "meal_type": "저녁"} for _ in range(count)]


def _pantry_coverage(recipe: dict, pantry_names: set[str]) -> float:
    ings = recipe.get("ingredients") or []
    if not ings:
        return 0.0
    matched = sum(
        1 for ing in ings
        if (ing.get("name") or "").strip()
        and any(ing["name"] in p or p in ing["name"] for p in pantry_names)
    )
    return matched / len(ings)


def _preference_match(recipe: dict, prefs: dict) -> float:
    cuisines = prefs.get("cuisines") or []
    favorites = prefs.get("favorites") or []
    dislikes = prefs.get("dislikes") or []
    name = recipe.get("name", "")

    # dislike 재료/요리 포함 시 강한 페널티
    ing_names = [(i.get("name") or "") for i in recipe.get("ingredients", [])]
    if any(d and (d in name or any(d in n for n in ing_names)) for d in dislikes):
        return 0.0

    score, factors = 0.0, 0
    if cuisines:
        factors += 1
        if recipe.get("cuisine_type") in cuisines:
            score += 1.0
    if favorites:
        factors += 1
        if any(f and f in name for f in favorites):
            score += 1.0
    return score / factors if factors else 0.6  # 선호 미지정 시 중립


def _nutrition_fit(recipe: dict, per_slot_target: dict) -> float:
    """레시피 1인분 매크로가 끼니별 목표 분량에 얼마나 부합하는지 (0~1)."""
    if not per_slot_target:
        return 0.6
    macros = {
        "kcal": recipe.get("calories", 0),
        "protein": recipe.get("protein", 0),
        "carb": recipe.get("carb", 0),
        "fat": recipe.get("fat", 0),
    }
    score = 0.0
    for k, w in NUTRIENT_WEIGHTS.items():
        t = per_slot_target.get(k, 0)
        if t <= 0:
            score += w
            continue
        ratio = macros[k] / t
        # 목표의 0.6~1.4 배면 적합. 멀수록 감점.
        fit = max(0.0, 1.0 - abs(ratio - 1.0))
        score += w * fit
    return round(score, 3)


def _goal_match(recipe: dict, dish_goals: list[str]) -> float:
    if not dish_goals:
        return 0.0
    name = recipe.get("name", "")
    return 1.0 if any(g and (g in name or name in g) for g in dish_goals) else 0.0


def _max_time_ok(recipe: dict, constraints: dict) -> bool:
    max_t = constraints.get("max_time")
    if not max_t:
        return True
    return int(recipe.get("time_min", 999)) <= max_t


def _excluded(recipe: dict, constraints: dict) -> bool:
    excl = set(constraints.get("exclude") or [])
    if not excl:
        return False
    # 요리명 직접 제외 (reflexion 재구성이 최악 슬롯을 빼는 경로)
    if any(term == recipe.get("name") for term in excl):
        return True
    for ing in recipe.get("ingredients", []):
        if any(term in (ing.get("name") or "") for term in excl):
            return True
    return False


async def meal_plan_composer_node(state: FridgeMateState) -> dict:
    pantry = state.get("pantry") or []
    pantry_names = {(p.get("name") or "").strip() for p in pantry if p.get("name")}
    prefs = state.get("preferences") or {}
    dish_goals = state.get("dish_goals") or []
    schedule = state.get("schedule") or {}
    targets = state.get("nutrient_targets") or {}
    constraints = state.get("constraints") or {}
    intake_text = state.get("intake_text") or ""
    people = max(state.get("people", 1), 1)
    locked = set(state.get("locked_dishes") or [])

    slots = _build_slots(schedule, dish_goals)
    # nutrient_targets = 1인 1끼 슬롯 목표. 레시피 1인분과 직접 비교 (judge 와 동일 스코프).
    per_slot_target = dict(targets) if targets else {}

    # RAG 우선 후보 풀 (ChromaDB recipe_db). 빈/실패 시 seed_recipes.json 직접 로드 fallback.
    pool = await _get_rag_candidates(
        intake_text=intake_text,
        dish_goals=dish_goals,
        prefs=prefs,
        constraints=constraints,
        k=max(20, len(slots) * 4),
    )
    if not pool:
        pool = _load_seed_recipes()

    recipes = [
        r for r in pool
        if not _excluded(r, constraints) and _max_time_ok(r, constraints)
    ]

    scored: list[dict] = []
    for r in recipes:
        cov = _pantry_coverage(r, pantry_names)
        pref = _preference_match(r, prefs)
        nutri = _nutrition_fit(r, per_slot_target)
        goal = _goal_match(r, dish_goals)
        score = (
            WEIGHTS["pantry"] * cov
            + WEIGHTS["pref"] * pref
            + WEIGHTS["nutri"] * nutri
            + WEIGHTS["goal"] * goal
        )
        reasons = []
        if cov >= 0.5:
            reasons.append(f"냉장고 충당 {cov:.0%}")
        if goal > 0:
            reasons.append("먹고 싶은 요리")
        if pref >= 1.0 and (prefs.get("cuisines") or prefs.get("favorites")):
            reasons.append("선호 맞음")
        if nutri >= 0.7 and per_slot_target:
            reasons.append("영양 적합")
        scored.append({
            "recipe": r,
            "cov": round(cov, 3),
            "score": round(score, 3),
            "rationale": ", ".join(reasons) or "균형 추천",
        })

    scored.sort(key=lambda c: c["score"], reverse=True)

    # 슬롯 배치: locked 우선 보존, 그 외엔 점수순으로 서로 다른 요리 배치.
    prev_plan = {(s.get("dish_name")): s for s in (state.get("meal_plan") or [])}
    used_ids: set[str] = set()
    meal_plan: list[dict] = []
    for slot in slots:
        prev = prev_plan.get(slot.get("meal_type"))  # best-effort
        # locked 요리가 이 슬롯에 있었으면 그대로
        locked_keep = next(
            (s for s in (state.get("meal_plan") or [])
             if s.get("dish_name") in locked
             and s.get("day") == slot["day"] and s.get("meal_type") == slot["meal_type"]),
            None,
        )
        if locked_keep:
            meal_plan.append(locked_keep)
            used_ids.add(locked_keep.get("recipe_id", ""))
            continue

        pick = next((c for c in scored if c["recipe"]["id"] not in used_ids), None)
        if pick is None and scored:
            pick = scored[0]  # 후보 소진 시 재사용 허용
        if pick is None:
            continue
        r = pick["recipe"]
        used_ids.add(r["id"])
        meal_plan.append({
            "day": slot["day"],
            "meal_type": slot["meal_type"],
            "dish_name": r["name"],
            "recipe_id": r["id"],
            "pantry_coverage": pick["cov"],
            "score": pick["score"],
            "rationale": pick["rationale"],
            # 이미 RAG/seed 에서 가져온 풀 레시피를 동봉 → recipe_node 가 재검색(resolve_dish) 생략.
            "recipe": r,
        })

    avg_cov = round(sum(s["pantry_coverage"] for s in meal_plan) / len(meal_plan), 3) if meal_plan else 0.0
    schedule_match = round(len(meal_plan) / max(len(slots), 1), 3)

    return {
        "meal_plan": meal_plan,
        "kpi_log": {
            **(state.get("kpi_log") or {}),
            "dishes_in_plan": len(meal_plan),
            "pantry_coverage": avg_cov,
            "schedule_match": schedule_match,
        },
    }
