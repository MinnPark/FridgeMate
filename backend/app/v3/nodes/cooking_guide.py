"""Cooking Guide 노드 — 실제 조리 가이드 생성 (final goal).

각 요리에 대해:
  - 단계별 체크리스트
  - 예상 소요 시간 (재료 손질 + 조리)
  - 병렬 작업 가능 여부 표시 (여러 요리 동시 조리 시)
  - 타이머 힌트
"""
from __future__ import annotations

from app.v3.state import FridgeMateState


async def cooking_guide_node(state: FridgeMateState) -> dict:
    recipes = state.get("recipes") or []
    progress: list[dict] = []

    for recipe in recipes:
        steps = []
        for idx, step_text in enumerate(recipe.get("steps", [])):
            steps.append({
                "step_no": idx + 1,
                "instruction": step_text,
                "done": False,
                "estimated_min": max(3, recipe.get("time_min", 20) // max(len(recipe.get("steps", [])), 1)),
            })
        progress.append({
            "dish_name": recipe["dish_name"],
            "total_time_min": recipe.get("time_min", 20),
            "steps": steps,
            "parallel_hint": f"{recipe['dish_name']} 1·2단계는 다른 요리 진행 중 병렬 가능",
        })

    return {"cooking_progress": progress}
