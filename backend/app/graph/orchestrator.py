from langgraph.graph import END, StateGraph

from app.agents.meal_agent import meal_agent
from app.agents.recipe_agent import recipe_agent
from app.agents.shopping_agent import shopping_agent
from app.graph.state import FridgeMateState
from app.prompts.supervisor_prompts import SUPERVISOR_ROUTING_PROMPT


def supervisor_router(state: FridgeMateState) -> str:
    """MVP router. Replace with LLM routing once model credentials are connected."""
    user_input = state.get("user_input", "")
    logs = state.get("logs", [])
    logs.append(
        {
            "node": "orchestrator",
            "event": "routing_prompt_loaded",
            "prompt": SUPERVISOR_ROUTING_PROMPT,
        }
    )
    state["logs"] = logs

    if state.get("meal_plan") and not state.get("cart_items"):
        return "shopping"

    if "레시피" in user_input or "요리" in user_input:
        return "recipe"

    return "meal"


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
