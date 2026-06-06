"""Reflexion 루프 — v3 재시도 분기.

judge FAIL 시 issue 종류에 따라 재구성 지점을 가른다:
  - 영양/재료/제약 문제 → meal_plan_composer (식단 재구성)
  - 예산 문제          → shopping_rank (대체재로 재구성)
상한: 3회. 초과 시 마지막(최저비용) 결과로 진행.
비용 가드: cost_tracker 임계 초과 시 즉시 종료.
"""
from __future__ import annotations

from langgraph.graph import END

from app.v3.state import FridgeMateState
from app.v3.tools.nutrition_calc import NUTRIENT_WEIGHTS  # 단일 출처 (중복 정의 제거)

MAX_REFLEXION = 3


def _nutrition_contribution(recipe: dict, targets: dict) -> float:
    """레시피가 영양 목표에 기여하는 정도 (높을수록 목표 충족에 도움).

    영양 실패(보통 부족)를 고치려면 기여가 가장 낮은 요리를 빼고 composer 가
    더 충실한 요리로 채우게 해야 한다 — '충당률 최저' 가 아니라 이 값 기준.
    """
    macros = {
        "kcal": recipe.get("calories", 0) or 0,
        "protein": recipe.get("protein", 0) or 0,
        "carb": recipe.get("carb", 0) or 0,
        "fat": recipe.get("fat", 0) or 0,
    }
    score = 0.0
    for key, weight in NUTRIENT_WEIGHTS.items():
        target = targets.get(key, 0)
        if target <= 0:
            continue
        score += weight * min(macros[key] / target, 1.5)
    return score


def reflexion_router(state: FridgeMateState) -> str:
    judge = state.get("judge_result") or {}
    if judge.get("pass", False):
        return "cart"
    if state.get("reflexion_count", 0) >= MAX_REFLEXION:
        return "cart"   # 상한 초과 — 마지막 결과로 진행
    return "reflect"


def reflect_target_router(state: FridgeMateState) -> str:
    """reflect 후 어디로 되돌아갈지. 예산만 문제면 장보기, 그 외엔 식단 재구성."""
    issues = (state.get("judge_result") or {}).get("issues") or []
    budget_issue = any("예산" in i for i in issues)
    other_issue = any(
        kw in i for i in issues for kw in ("영양", "재료 충분도", "제약")
    )
    if budget_issue and not other_issue:
        return "shopping_rank"
    return "meal_plan_composer"


async def reflect_node(state: FridgeMateState) -> dict:
    judge = state.get("judge_result") or {}
    issues = judge.get("issues") or []
    target = reflect_target_router(state)

    critique = (
        "다음 문제를 개선해 재구성하세요:\n- "
        + "\n- ".join(issues)
        + f"\n\n재구성 지점: {target}"
    )

    patch: dict = {
        "reflexion_count": 1,
        "judge_result": {**judge, "critique": critique},
    }

    if target == "shopping_rank":
        # 부족 재료를 대체재로 시도 + 후보군 무효화(재생성 유도)
        missing = state.get("missing_ingredients") or []
        updated = []
        for item in missing:
            new_item = dict(item)
            if item.get("decision") == "buy":
                new_item["decision"] = "substitute"
            updated.append(new_item)
        patch["missing_ingredients"] = updated
        patch["shopping_candidates"] = []   # _stale 유도 → 대체재 우선 재순위
    else:
        # 식단 재구성: 실패 원인에 맞는 슬롯을 빼야 composer 가 올바른 방향으로 채운다.
        #   - 영양 실패  → 영양 기여 최저 슬롯 제거 (충당률 최저가 아님 — 레버 정렬)
        #   - 그 외(재료/제약) → 충당률 최저 슬롯 제거
        # locked_dishes 는 사용자가 고정한 것 — 절대 제외 후보로 삼지 않는다.
        plan = state.get("meal_plan") or []
        locked = set(state.get("locked_dishes") or [])
        removable = [s for s in plan if s.get("dish_name") not in locked]
        if removable:
            nutrition_issue = any("영양" in i for i in issues)
            if nutrition_issue:
                recipe_by_name = {r.get("dish_name"): r for r in (state.get("recipes") or [])}
                targets = state.get("nutrient_targets") or {}
                worst = min(
                    removable,
                    key=lambda s: _nutrition_contribution(
                        recipe_by_name.get(s.get("dish_name"), {}), targets
                    ),
                )
            else:
                worst = min(removable, key=lambda s: s.get("pantry_coverage", 0.0))
            constraints = dict(state.get("constraints") or {})
            excl = list(constraints.get("exclude") or [])
            if worst.get("dish_name") and worst["dish_name"] not in excl:
                excl.append(worst["dish_name"])
            constraints["exclude"] = excl
            patch["constraints"] = constraints
            patch["meal_plan"] = []   # 강제 재구성

    return patch


def cost_guard_router(state: FridgeMateState) -> str:
    tracker = state.get("cost_tracker") or {}
    if (
        tracker.get("input_tokens", 0) > 100_000
        or tracker.get("output_tokens", 0) > 20_000
        or tracker.get("calls", 0) > 30
    ):
        return END  # type: ignore[return-value]
    return "continue"
