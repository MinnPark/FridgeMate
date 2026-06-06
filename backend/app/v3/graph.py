"""LangGraph StateGraph — v3 통합 흐름.

START → orchestrator → pantry(★진입: 냉장고) → intake(선호·요리목표·패턴·영양)
     → meal_plan_composer(★식단 구성) → recipe(식단 각 요리) → gap_calc(식단 부족재료)
     → shopping_rank(상품 후보군) → judge(영양·예산·패턴·제약)
          ├─[FAIL,<3회]→ reflect ─┬→ meal_plan_composer (영양/재료/제약 재구성)
          │                       └→ shopping_rank      (예산 재구성)
          └─[PASS or 3회]→ cart → cooking_guide → END
"""
from __future__ import annotations

import os
from pathlib import Path

from langgraph.graph import END, StateGraph

from app.v3.loops.reflexion import (
    reflect_node,
    reflect_target_router,
    reflexion_router,
)
from app.v3.nodes.cart import cart_node
from app.v3.nodes.cooking_guide import cooking_guide_node
from app.v3.nodes.gap_calc import gap_calc_node
from app.v3.nodes.intake import intake_node
from app.v3.nodes.judge import judge_node
from app.v3.nodes.meal_plan_composer import meal_plan_composer_node
from app.v3.nodes.orchestrator import orchestrator_node
from app.v3.nodes.pantry import pantry_node
from app.v3.nodes.recipe import recipe_node
from app.v3.nodes.shopping_rank import shopping_rank_node
from app.v3.state import FridgeMateState

NODE_NAMES = (
    "orchestrator", "pantry", "intake", "meal_plan_composer", "recipe",
    "gap_calc", "shopping_rank", "judge", "reflect", "cart", "cooking_guide",
)


def build_state_graph() -> StateGraph:
    g = StateGraph(FridgeMateState)

    g.add_node("orchestrator", orchestrator_node)
    g.add_node("pantry", pantry_node)
    g.add_node("intake", intake_node)
    g.add_node("meal_plan_composer", meal_plan_composer_node)
    g.add_node("recipe", recipe_node)
    g.add_node("gap_calc", gap_calc_node)
    g.add_node("shopping_rank", shopping_rank_node)
    g.add_node("judge", judge_node)
    g.add_node("reflect", reflect_node)
    g.add_node("cart", cart_node)
    g.add_node("cooking_guide", cooking_guide_node)

    g.set_entry_point("orchestrator")
    g.add_edge("orchestrator", "pantry")
    g.add_edge("pantry", "intake")
    g.add_edge("intake", "meal_plan_composer")
    g.add_edge("meal_plan_composer", "recipe")
    g.add_edge("recipe", "gap_calc")
    g.add_edge("gap_calc", "shopping_rank")
    g.add_edge("shopping_rank", "judge")

    g.add_conditional_edges(
        "judge",
        reflexion_router,
        {"reflect": "reflect", "cart": "cart"},
    )
    g.add_conditional_edges(
        "reflect",
        reflect_target_router,
        {"meal_plan_composer": "meal_plan_composer", "shopping_rank": "shopping_rank"},
    )
    g.add_edge("cart", "cooking_guide")
    g.add_edge("cooking_guide", END)

    return g


def get_checkpointer():
    kind = os.getenv("CHECKPOINTER_TYPE", "memory").lower()

    if kind == "memory":
        from langgraph.checkpoint.memory import MemorySaver
        return MemorySaver()

    if kind == "postgres":
        from langgraph.checkpoint.postgres import PostgresSaver
        saver = PostgresSaver.from_conn_string(os.environ["DATABASE_URL"])
        saver.setup()
        return saver

    if kind == "sqlite":
        import aiosqlite
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
        db_path = Path(os.getenv("CHECKPOINT_DB_PATH", "./data/checkpoints.sqlite"))
        db_path.parent.mkdir(parents=True, exist_ok=True)
        return AsyncSqliteSaver(aiosqlite.connect(str(db_path)))

    raise ValueError(f"Unknown CHECKPOINTER_TYPE={kind}")


def compile_graph():
    return build_state_graph().compile(checkpointer=get_checkpointer())
