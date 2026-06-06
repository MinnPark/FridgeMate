"""Nutrition score 계산 — judge_node 가 사용.

식단 평균 1인분 매크로 vs 1인 1끼 슬롯 목표 비교. **Tool 수치 기반 (LLM 추정 금지)**.
4대 매크로 가중치: kcal 0.3 / protein 0.4 / carb 0.15 / fat 0.15.

Function calling 도입 시 (sprint_status #22 deferred, 데이터 후) tool spec:
  name        : calculate_nutrition_score
  description : 식단 평균 1인분 매크로가 사용자 영양 목표(슬롯당)에 얼마나 부합하는지 계산
  parameters  : {recipes: [{calories,protein,carb,fat}], targets: {kcal,protein,carb,fat}}
  returns     : float (0~1, 1에 가까울수록 fit)
"""
from __future__ import annotations

NUTRIENT_WEIGHTS = {"kcal": 0.3, "protein": 0.4, "carb": 0.15, "fat": 0.15}


def compute_nutrition_score(recipes: list[dict], targets: dict) -> float:
    """식단 평균 매크로 vs 슬롯 목표. composer/judge 동일 스코프 (1인 1끼)."""
    if not targets or not recipes:
        return 1.0
    n = len(recipes)
    avg = {
        "kcal": sum((r.get("calories", 0) or 0) for r in recipes) / n,
        "protein": sum((r.get("protein", 0) or 0) for r in recipes) / n,
        "carb": sum((r.get("carb", 0) or 0) for r in recipes) / n,
        "fat": sum((r.get("fat", 0) or 0) for r in recipes) / n,
    }
    score = 0.0
    for key, weight in NUTRIENT_WEIGHTS.items():
        target = targets.get(key, 0)
        if target <= 0:
            # 목표 미지정 → 가중치만큼 가산 (제약 없음 = 만점)
            score += weight
            continue
        ratio = avg[key] / target
        # 목표 대비 0.5~1.5 배 안이면 가점, 멀수록 감점
        fit = max(0.0, 1.0 - abs(ratio - 1.0) / 0.5)
        score += weight * min(fit, 1.0)
    return round(score, 3)
