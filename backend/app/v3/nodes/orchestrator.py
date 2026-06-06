"""Orchestrator 노드 — 입력 검증 + kpi_log/cost_tracker 초기화 (v3).

v3 진입점은 fridge_items. intake_text/preferences/dish_goals/schedule 는 옵셔널.
"""
from __future__ import annotations

from app.v3.state import FridgeMateState, initial_cost_tracker, initial_kpi_log


async def orchestrator_node(state: FridgeMateState) -> dict:
    errors: list[str] = []

    if not state.get("fridge_items"):
        errors.append("fridge_items 비어 있음 — 냉장고에 뭐 있는지 알려주세요")
    if state.get("budget", 0) <= 0:
        errors.append("budget 0 이하")
    if state.get("people", 0) <= 0:
        errors.append("people 0 이하")

    return {
        "errors": errors,
        "kpi_log": initial_kpi_log(),
        "cost_tracker": initial_cost_tracker(),
    }
