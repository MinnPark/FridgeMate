"""Judge 노드 — v3 검증 (영양 강제 복귀).

검증 항목 (모두 PASS 영향 — 영양이 advisory 에서 강제로 복귀):
  1. 영양 충족        (강제 — nutrition_score < 임계 시 FAIL → meal_plan 재구성)
  2. 예산 충족        (강제 — 초과 시 FAIL → shopping 재구성)
  3. 재료 충분도      (강제 — coverage < 0.5 시 FAIL)
  4. 제약 위반        (강제 — exclude 재료 사용 시 즉시 FAIL)
  5. 끼니 슬롯 충족    (schedule_fit — 점수 반영)

영양 계산은 Tool 수치(레시피 레벨 매크로) 기반만. LLM 추정 금지.
suggestion: opus 4.7 자연어 한 줄 (cache_control). LLM 비활성 시 휴리스틱.
"""
from __future__ import annotations

import json

from app.v3.state import FridgeMateState
from app.rag._llm import call_llm
from app.v3.tools.nutrition_calc import compute_nutrition_score

PASS_INGREDIENT_COVERAGE = 0.30   # 냉장고 우선 컷오프와 동일 (CLAUDE.md 5a)
PASS_NUTRITION_SCORE = 0.60


def _check_constraints(recipes: list[dict], constraints: dict) -> tuple[bool, list[str]]:
    excluded = set(constraints.get("exclude") or [])
    violations: list[str] = []
    for recipe in recipes:
        for ing in recipe.get("ingredients", []):
            for term in excluded:
                if term in ing.get("name", ""):
                    violations.append(f"{recipe.get('dish_name','')}: '{term}' 제약 위반")
    return (not violations), violations


async def judge_node(state: FridgeMateState) -> dict:
    recipes = state.get("recipes") or []
    targets = state.get("nutrient_targets") or {}
    constraints = state.get("constraints") or {}

    kpi = state.get("kpi_log") or {}
    coverage = kpi.get("ingredient_coverage", 1.0)
    budget_ok = kpi.get("budget_compliance", True)
    schedule_fit = kpi.get("schedule_match", 1.0)

    constraint_ok, violations = _check_constraints(recipes, constraints)
    nutrition_score = compute_nutrition_score(recipes, targets)
    nutrition_ok = nutrition_score >= PASS_NUTRITION_SCORE

    # ── FAIL(=Reflexion 발동) 사유 = 제약 한정 ────────────────────────────────
    # 영양·재료충당·예산은 모두 advisory(점수 계산·화면 표시만, FAIL 아님).
    #  - 영양/재료충당: seed 로는 목표를 못 맞춰 매 패스 RAG 재검색이 반복되던 문제로 제외(이전 변경).
    #  - 예산: v3 의 목 가격(MOCK_PACKAGE_PRICE) 기반이라 사용자에게 안 닿는 헛루프였다.
    #    실제 예산 회고는 실가격이 확정되는 프론트(CartExecutionCard → /shopping/budget-reflexion)
    #    한 곳에서만 수행한다. 따라서 그래프 안에서는 예산으로 루프를 돌지 않는다.
    # issues 에는 라우팅 사유(제약→meal_plan_composer)만 담는다.
    issues: list[str] = []
    if not constraint_ok:
        issues.extend(violations)

    advisory: list[str] = []        # 표시용(루프 비유발)
    if not nutrition_ok:
        advisory.append(f"영양 목표 미달: {nutrition_score:.0%} (목표 {PASS_NUTRITION_SCORE:.0%})")
    if coverage < PASS_INGREDIENT_COVERAGE:
        advisory.append(f"재료 충분도 낮음: {coverage:.0%}")
    if not budget_ok:
        advisory.append("예산 초과(추정) — 실제 조정은 장보기 단계에서")

    score = (
        nutrition_score * 0.30
        + (1.0 if budget_ok else 0.4) * 0.25
        + coverage * 0.25
        + schedule_fit * 0.10
        + (1.0 if constraint_ok else 0.0) * 0.10
    )
    # PASS 게이트: 제약만 (영양·재료충당·예산은 advisory).
    passed = constraint_ok

    # suggestion 은 advisory 까지 보고 조언 — 표시용일 뿐 라우팅(reflect_target_router)은 issues 만 본다.
    # 비용 가드: Reflexion 실패 패스(매 루프)마다 느린 opus 를 부르면 4회×~4초가 든다.
    # LLM 조언은 최종 PASS 일 때만 생성하고, 실패/루프 중엔 휴리스틱 한 줄로 즉답한다.
    suggestion = await _build_suggestion(issues + advisory, recipes, passed, use_llm=passed)

    return {
        "judge_result": {
            "pass": passed,
            "score": round(score, 3),
            "score_breakdown": {
                "nutrition":    nutrition_score,
                "budget":       1.0 if budget_ok else 0.4,
                "schedule_fit": round(schedule_fit, 3),
                "coverage":     round(coverage, 3),
                "constraint":   1.0 if constraint_ok else 0.0,
            },
            "issues": issues,
            "advisory": advisory,   # 영양·재료충당(표시용, Reflexion 비유발)
            "suggestion": suggestion,
        },
        "kpi_log": {
            **kpi,
            "nutrition_score": nutrition_score,
            "e2e_success": passed,
            # top-level reflexion_count (Annotated 누적) 를 KPI 에도 동기 (이전 0 고정 버그 해소)
            "reflexion_count": state.get("reflexion_count", 0),
        },
    }


async def _build_suggestion(
    issues: list[str], recipes: list[dict], passed: bool, *, use_llm: bool = True
) -> str:
    if passed and not issues:
        offline = "영양·예산·재료 모두 OK — 바로 만들어요!"
    elif any("영양" in i for i in issues):
        offline = "영양 목표에 안 맞아요. 단백질 높은 요리로 한 끼를 바꾸면 식단 균형이 좋아져요."
    elif any("예산" in i for i in issues):
        offline = "예산이 빠듯해요. 후보군에서 비싼 재료를 대체상품으로 바꿔보세요."
    elif any("재료 충분도" in i for i in issues):
        offline = "냉장고 재료가 부족해요. 충당률 높은 다른 요리로 식단을 조정하거나 부족 재료만 사세요."
    else:
        offline = "제약 조건이 충돌해요. exclude 항목을 다시 확인해주세요."

    # 루프/실패 패스에서는 LLM 생략(즉답). 최종 표시 시점에만 opus 로 다듬는다.
    if not use_llm:
        return offline

    dish_names = ", ".join(r.get("dish_name", "") for r in recipes[:4])
    user_msg = json.dumps(
        {"issues": issues, "passed": passed, "dishes": dish_names},
        ensure_ascii=False,
    )
    return await call_llm(
        system_prompt_name="judge_suggestion",
        user_content=user_msg,
        model_env="ANTHROPIC_MODEL_JUDGE",
        fallback=offline,
        max_tokens=200,
    )
