"""FridgeMate LangGraph State — v3 통합 흐름.

진입점 = fridge_items (냉장고). intake 가 선호도/요리목표/패턴/영양을 파싱하고,
meal_plan_composer 가 식단(meal_plan)을 구성한다. 요리 단건이 아니라 식단 단위.
변경 시 .claude/memory/state_schema.md 동시 갱신.
"""
from __future__ import annotations

import operator
import time
from typing import Annotated, NotRequired, TypedDict


class NutrientTargets(TypedDict):
    kcal: int
    protein: int
    carb: int
    fat: int


class Preferences(TypedDict, total=False):
    """선호도 — 식단 구성 가중치."""
    cuisines: list[str]      # 선호 장르 ["한식", "양식"]
    spice_level: int         # 0~3
    dislikes: list[str]      # 기피 재료/요리
    favorites: list[str]     # 선호 요리 (boost)


class Schedule(TypedDict, total=False):
    """라이프스타일 패턴 — 식단의 끼니 슬롯 정의."""
    days: list[str]          # ["토", "일"] / ["주중"]
    meals: list[str]         # ["아침", "점심", "저녁"]


class MealSlot(TypedDict):
    """식단의 한 칸 — meal_plan_composer 출력."""
    day: str
    meal_type: str
    dish_name: str
    recipe_id: str
    pantry_coverage: float
    score: float
    rationale: NotRequired[str]


class ShoppingCandidate(TypedDict):
    """부족 재료 1건에 대한 상품 후보 (순위 매김)."""
    ingredient: str
    rank: int                # 1=최우선 후보
    product_name: str
    price: int
    unit_price: NotRequired[float]
    delivery: NotRequired[str]
    product_url: str
    substituted: bool
    selected: bool           # 장바구니 선택점에서 토글


def merge_costs(left: dict, right: dict) -> dict:
    result = dict(left or {})
    for key in ("input_tokens", "output_tokens", "calls"):
        result[key] = (result.get(key, 0) or 0) + (right.get(key, 0) or 0)
    result["started_at"] = (left or {}).get("started_at") or right.get("started_at") or time.time()
    return result


class FridgeMateState(TypedDict):
    # 입력 (불변) — v3 진입점은 냉장고
    user_id: str
    thread_id: str
    fridge_items: list[str]                  # ★ 진입점
    preferences: NotRequired[Preferences]    # 선호도
    dish_goals: NotRequired[list[str]]       # 먹을 요리 목표(들) — 식단 시드 (옵셔널)
    schedule: NotRequired[Schedule]          # 라이프스타일 패턴 (끼니 슬롯)
    intake_text: NotRequired[str]            # 자연어 한 줄 (intake 가 파싱)
    diet_goals: list[str]                    # 영양 목표 라벨 ["고단백"]
    nutrient_targets: NutrientTargets        # 영양 수치 (v3 강제 검증)
    budget: int
    people: int
    constraints: dict                        # {"exclude":[...], "max_time":int}

    # 단계별 결과
    pantry: list[dict]
    meal_plan: list[MealSlot]                # ★ meal_plan_composer 출력 (식단)
    recipes: list[dict]                      # 식단 각 요리 풀 레시피
    missing_ingredients: list[dict]          # 식단 전체 부족 재료
    shopping_candidates: list[ShoppingCandidate]  # ★ 후보군 (순위)
    shopping_list: list[dict]                # 사용자 최종 선택 (결제 대상)
    cart_result: dict
    cooking_progress: list[dict]

    # 검증
    judge_result: dict                       # 영양+예산+패턴+제약
    reflexion_count: Annotated[int, operator.add]

    # 대화 (B 패턴)
    messages: NotRequired[list[dict]]
    locked_dishes: NotRequired[list[str]]    # "이 끼니는 그대로 둬"

    # 메타
    errors: Annotated[list[str], operator.add]
    cost_tracker: Annotated[dict, merge_costs]
    kpi_log: dict


def initial_kpi_log() -> dict:
    return {
        "nutrition_score":   0.0,   # 영양 목표 충족률 (목표 ≥ 0.90)
        "pantry_coverage":   0.0,   # 재고 활용 (목표 ≥ 0.5)
        "schedule_match":    1.0,   # 끼니 슬롯 충족률 (목표 1.0)
        "ingredient_coverage": 0.0,
        "budget_compliance": True,  # 목표 ≥ 0.95
        "citation_included": True,  # 목표 1.0
        "e2e_success":       True,  # 목표 ≥ 0.85
        "dishes_in_plan":    0,     # 식단 요리 수
        "reflexion_count":   0,
        "substitutes_used":  0,
    }


def initial_cost_tracker() -> dict:
    return {
        "input_tokens": 0,
        "output_tokens": 0,
        "calls": 0,
        "started_at": time.time(),
    }
