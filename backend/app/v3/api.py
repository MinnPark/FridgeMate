"""v3 멀티 엔드포인트 라우터 (additive). 기존 /chat 안 건드리고 /api/* 추가.

/api/compose : 냉장고+선호/패턴/영양 -> 식단(meal_plan) 제안
/api/run     : (조정된) 식단 -> 부족재료 -> 후보군 -> judge -> 결제 -> 조리 (풀 v3 그래프)
/api/stream  : SSE
/api/kpi     : KPI 집계
main.py 에서 app.include_router(v3_router) 로 연결.
"""
from __future__ import annotations

import json
import os
import time
import uuid

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.v3.graph import NODE_NAMES, compile_graph
from app.v3.nodes.intake import intake_node
from app.v3.nodes.meal_plan_composer import meal_plan_composer_node
from app.v3.nodes.orchestrator import orchestrator_node
from app.v3.nodes.pantry import pantry_node
from app.v3.state import NutrientTargets, initial_cost_tracker, initial_kpi_log

router = APIRouter()
graph = compile_graph()


class Constraints(BaseModel):
    exclude: list[str] = Field(default_factory=list)
    max_time: int | None = None


class PreferencesIn(BaseModel):
    cuisines: list[str] = Field(default_factory=list)
    spice_level: int | None = None
    dislikes: list[str] = Field(default_factory=list)
    favorites: list[str] = Field(default_factory=list)


class ScheduleIn(BaseModel):
    days: list[str] = Field(default_factory=list)
    meals: list[str] = Field(default_factory=list)


class MealSlotIn(BaseModel):
    day: str = "오늘"
    meal_type: str = "저녁"
    dish_name: str
    recipe_id: str | None = None
    pantry_coverage: float = 0.0
    score: float = 0.0


class ShoppingCandidateIn(BaseModel):
    ingredient: str
    rank: int = 1
    product_name: str = ""
    price: int = 0
    unit_price: float | None = None
    delivery: str | None = None
    product_url: str = ""
    substituted: bool = False
    selected: bool = True
    qty: float = 1
    unit: str = ""
    packages: int = 1
    used_in: list[str] = Field(default_factory=list)


class RunRequest(BaseModel):
    user_id: str = "anon"
    thread_id: str | None = None
    fridge_items: list[str] = Field(default_factory=list)
    intake_text: str | None = None
    preferences: PreferencesIn | None = None
    dish_goals: list[str] = Field(default_factory=list)
    schedule: ScheduleIn | None = None
    diet_goals: list[str] = Field(default_factory=list)
    nutrient_targets: NutrientTargets = Field(
        default_factory=lambda: {"kcal": 430, "protein": 25, "carb": 35, "fat": 20}  # type: ignore[arg-type]
    )
    budget: int = 30_000
    people: int = 2
    constraints: Constraints = Field(default_factory=Constraints)
    meal_plan: list[MealSlotIn] = Field(default_factory=list)
    shopping_candidates: list[ShoppingCandidateIn] = Field(default_factory=list)
    locked_dishes: list[str] = Field(default_factory=list)


def _build_initial_state(req: RunRequest, thread_id: str) -> dict:
    return {
        "user_id": req.user_id, "thread_id": thread_id,
        "fridge_items": req.fridge_items, "intake_text": req.intake_text or "",
        "preferences": req.preferences.model_dump(exclude_none=True) if req.preferences else {},
        "dish_goals": req.dish_goals,
        "schedule": req.schedule.model_dump(exclude_none=True) if req.schedule else {},
        "diet_goals": req.diet_goals, "nutrient_targets": req.nutrient_targets,
        "budget": req.budget, "people": req.people,
        "constraints": req.constraints.model_dump(exclude_none=True),
        "locked_dishes": req.locked_dishes, "pantry": [],
        "meal_plan": [s.model_dump(exclude_none=True) for s in req.meal_plan],
        "recipes": [], "missing_ingredients": [],
        "shopping_candidates": [c.model_dump(exclude_none=True) for c in req.shopping_candidates],
        "shopping_list": [], "cart_result": {}, "cooking_progress": [],
        "judge_result": {}, "reflexion_count": 0, "errors": [],
        "cost_tracker": initial_cost_tracker(), "kpi_log": initial_kpi_log(),
    }


@router.post("/api/compose")
async def compose(req: RunRequest) -> dict:
    thread_id = req.thread_id or str(uuid.uuid4())
    state = _build_initial_state(req, thread_id)
    state["meal_plan"] = []
    for node in (orchestrator_node, pantry_node, intake_node, meal_plan_composer_node):
        patch = await node(state)
        if patch:
            state.update(patch)
        if state.get("errors"):
            break
    return {
        "thread_id": thread_id, "pantry": state.get("pantry") or [],
        "preferences": state.get("preferences") or {}, "schedule": state.get("schedule") or {},
        "dish_goals": state.get("dish_goals") or [], "meal_plan": state.get("meal_plan") or [],
        "kpi_log": state.get("kpi_log") or {}, "errors": state.get("errors") or [],
    }


@router.post("/api/run")
async def run_pipeline(req: RunRequest) -> dict:
    thread_id = req.thread_id or str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}
    result = await graph.ainvoke(_build_initial_state(req, thread_id), config=config)
    try:
        from app.v3.monitoring.kpi_collector import record_run
        record_run(thread_id=thread_id, user_id=req.user_id, kpi_log=result.get("kpi_log") or {})
    except Exception as exc:  # noqa: BLE001
        print(f"[kpi] record_run 실패 (무시): {exc}")
    return {"thread_id": thread_id, **result}


@router.get("/api/kpi")
async def get_kpi(limit: int | None = None) -> dict:
    from app.v3.monitoring.kpi_collector import KPI_TARGETS, aggregate
    agg = aggregate(limit=limit)
    return {**agg, "targets": {k: {"kind": v[0], "goal": v[1]} for k, v in KPI_TARGETS.items()}}


SESSION_TIMEOUT = int(os.getenv("SESSION_TIMEOUT_SECONDS", "180"))


def _sse(event: str, data: dict) -> bytes:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n".encode("utf-8")


@router.post("/api/stream")
async def stream_pipeline(req: RunRequest):
    thread_id = req.thread_id or str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}
    initial_state = _build_initial_state(req, thread_id)
    started = time.time()
    node_set = set(NODE_NAMES)

    async def gen():
        yield _sse("session_start", {"thread_id": thread_id})
        try:
            async for event in graph.astream_events(initial_state, config=config, version="v2"):
                if time.time() - started > SESSION_TIMEOUT:
                    yield _sse("budget_abort", {"reason": "timeout", "limit": SESSION_TIMEOUT})
                    break
                etype, name = event.get("event", ""), event.get("name", "")
                if etype == "on_chain_start" and name in node_set:
                    yield _sse("node_start", {"node": name})
                elif etype == "on_chain_end" and name in node_set:
                    patch = event.get("data", {}).get("output") or {}
                    yield _sse("node_end", {"node": name, "patch_keys": list(patch.keys()) if isinstance(patch, dict) else []})
        except Exception as exc:  # noqa: BLE001
            yield _sse("error", {"message": str(exc)})
        finally:
            yield _sse("done", {"thread_id": thread_id, "elapsed_sec": round(time.time() - started, 2)})

    return StreamingResponse(gen(), media_type="text/event-stream")
