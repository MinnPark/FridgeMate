"""Gap Calc 노드 — 식단 재료 vs 재고 → 부족 재료 산출 (v3).

  - 필요 총량 = Σ 레시피 재료량 × 인원수
  - 재고 가용량 = pantry parsed qty
  - 부족분 = max(필요 - 재고, 0)

단위 정합 규칙 (v3):
  - 단위 일치(또는 한쪽 미지정) → 수치 뺄셈
  - 단위 불일치 (e.g. "100g" 필요 vs "1쪽" 보유) → 변환표 없음, 정량 비교 불가 →
    보유는 하므로 covered 로 간주 + `unit_mismatch=True` 로 표시 (사용자가 식단 카드에서 확인 가능).
  - 재고에 아예 없음 → 전량 부족 (수치 정합과 무관).
"""
from __future__ import annotations

from app.v3.state import FridgeMateState
from app.v3.tools.missing_calc import compute_missing


async def gap_calc_node(state: FridgeMateState) -> dict:
    missing, coverage, unit_mismatch = compute_missing(
        pantry=state.get("pantry") or [],
        recipes=state.get("recipes") or [],
        people=state.get("people", 1),
    )
    return {
        "missing_ingredients": missing,
        "kpi_log": {
            **state.get("kpi_log", {}),
            "ingredient_coverage": coverage,
            "unit_mismatch_count": unit_mismatch,
        },
    }
