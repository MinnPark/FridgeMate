from langgraph.graph import END, StateGraph

from app.agents.meal_agent import meal_agent
from app.agents.recipe_agent import recipe_agent
from app.agents.shopping_agent import shopping_agent
from app.graph.state import FridgeMateState
from app.llm import generate_json
from app.prompts.supervisor_prompts import SUPERVISOR_ROUTING_PROMPT
from app.tools.logging_tools import append_log


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
    user_input = state.get("user_input", "")
    if state.get("meal_plan") and not state.get("cart_items"):
        return "shopping"
    if "레시피" in user_input or "요리" in user_input:
        return "recipe"
    return "meal"


def _fallback_next_steps(route: str) -> list[str]:
    if route == "meal":
        return ["Meal Agent", "Recipe Agent", "Shopping Agent"]
    if route == "recipe":
        return ["Recipe Agent", "Shopping Agent"]
    return ["Shopping Agent"]


def build_graph():
    graph = StateGraph(FridgeMateState)

    graph.add_node("meal", meal_agent)
    graph.add_node("recipe", recipe_agent)
    graph.add_node("shopping", shopping_agent)

    graph.set_conditional_entry_point(
        supervisor_router,
        {
            "meal": "meal",
            "recipe": "recipe",
            "shopping": "shopping",
        },
    )

    graph.add_edge("meal", "shopping")
    graph.add_edge("recipe", "shopping")
    graph.add_edge("shopping", END)

    return graph.compile()
