from langgraph.graph import END, StateGraph

from app.agents.meal_agent import meal_agent
from app.agents.pantry_agent import pantry_agent
from app.agents.recipe_agent import recipe_agent
from app.agents.shopping_agent import shopping_agent
from app.graph.state import FridgeMateState
from app.llm import generate_json
from app.prompts.supervisor_prompts import SUPERVISOR_ROUTING_PROMPT
from app.tools.logging_tools import append_log
from app.tools.nutrition_tools import verify_nutrition_goal_tool     # ← 추가
from app.tools.shopping_tools import search_coupang_products_tool    # ← 추가

# ── Tool Calling 목록 (main.py에서도 import해서 사용) ──────────────────────
FRIDGEMATE_TOOLS = [
    verify_nutrition_goal_tool,   # 영양 목표 검증 (nutrition_goal 있을 때)
    search_coupang_products_tool, # 장보기 검색 (missing 있고 today 아닐 때)
]


def supervisor_router(state: FridgeMateState) -> str:
    """Supervisor router with LLM-ready structured output and fallback rules."""
    fallback_route = _fallback_route(state)
    decision = generate_json(
        system_prompt=SUPERVISOR_ROUTING_PROMPT,
        user_prompt=(
            f"사용자 입력: {state.get('user_input', '')}\n"
            f"현재 meal_plan 존재: {bool(state.get('meal_plan'))}\n"
            f"현재 cart_items 존재: {bool(state.get('cart_items'))}\n"
            "가장 적절한 다음 agent route를 결정하세요."
        ),
        fallback={
            "route": fallback_route,
            "reason": "키워드와 현재 state 기반 fallback 라우팅입니다.",
            "next_steps": _fallback_next_steps(fallback_route),
        },
    )
    route = decision.get("route", fallback_route)
    if route not in {"meal", "recipe", "shopping"}:
        route = fallback_route
    # Meal Agent는 Recipe Agent의 selected_recipes를 전제로 식단과 영양을 계산한다.
    # 전체 분석의 첫 라우팅에서 meal을 선택하면 RAG가 건너뛰어져 영양값이 모두 0이 된다.
    if route == "meal" and state.get("pantry_items") and not state.get("selected_recipes"):
        route = "recipe"

    state["route"] = route
    state["logs"] = append_log(
        state.get("logs"),
        node="orchestrator",
        event="supervisor_routed",
        prompt=SUPERVISOR_ROUTING_PROMPT,
        route=route,
        reason=decision.get("reason"),
        next_steps=decision.get("next_steps"),
        llm=decision.get("_meta"),
    )
    return route


def _fallback_route(state: FridgeMateState) -> str:
    if state.get("meal_plan") and not state.get("cart_items"):
        return "shopping"
    if state.get("selected_recipes"):
        return "meal"
    # 식단/레시피 분석 모두 먼저 RAG 검색이 필요하다.
    return "recipe"


def _fallback_next_steps(route: str) -> list[str]:
    if route == "meal":
        return ["Meal Agent", "Shopping Agent"]
    if route == "recipe":
        return ["Recipe Agent", "Meal Agent", "Shopping Agent"]
    return ["Shopping Agent"]


def build_graph():
    """
    기존 /chat 전용 그래프
    supervisor_router 기반 동적 라우팅
    변경 없음
    """
    graph = StateGraph(FridgeMateState)

    graph.add_node("pantry",   pantry_agent)
    graph.add_node("meal",     meal_agent)
    graph.add_node("recipe",   recipe_agent)
    graph.add_node("shopping", shopping_agent)

    graph.set_entry_point("pantry")

    graph.add_conditional_edges(
        "pantry",
        supervisor_router,
        {
            "meal":     "meal",
            "recipe":   "recipe",
            "shopping": "shopping",
        },
    )

    graph.add_edge("recipe",   "meal")
    graph.add_edge("meal",     "shopping")
    graph.add_edge("shopping", END)

    return graph.compile()


def build_tool_graph():
    """
    /chat/tool 전용 그래프
    supervisor_router 없이 선형 파이프라인

    목적:
      pantry → recipe → meal → shopping → END
      missing_ingredients, selected_recipes 확보
      이후 LLM이 FRIDGEMATE_TOOLS 중 선택적 호출
    """
    graph = StateGraph(FridgeMateState)

    graph.add_node("pantry",   pantry_agent)
    graph.add_node("recipe",   recipe_agent)
    graph.add_node("meal",     meal_agent)
    graph.add_node("shopping", shopping_agent)

    graph.set_entry_point("pantry")

    # 선형 파이프라인 (supervisor 없음)
    graph.add_edge("pantry",   "recipe")
    graph.add_edge("recipe",   "meal")
    graph.add_edge("meal",     "shopping")
    graph.add_edge("shopping", END)

    return graph.compile()
