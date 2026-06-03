from app.agents.recipe_agent import retrieve_recipes
from app.graph.state import FridgeMateState
from app.prompts.meal_prompts import MEAL_EXECUTE_PROMPT, MEAL_PLAN_PROMPT
from app.tools.nutrition_tools import verify_nutrition_goal
from app.tools.pantry_tools import parse_pantry_items


def create_weekly_plan(state: FridgeMateState) -> dict:
    pantry_items = state.get("pantry_items") or parse_pantry_items(state.get("user_input", ""))
    return {
        "strategy": "Plan-and-Execute",
        "days": [
            {
                "day": "mon",
                "meals": [
                    {
                        "slot": "lunch",
                        "name": "두부 된장찌개",
                        "reason": "냉장고 재료를 우선 사용하고 단백질을 보강합니다.",
                    },
                    {
                        "slot": "dinner",
                        "name": "계란 채소 비빔밥",
                        "reason": "남은 채소와 계란을 사용해 식재료 폐기를 줄입니다.",
                    },
                ],
            }
        ],
        "pantry_used_first": [item["name"] for item in pantry_items],
    }


def execute_meal_plan(plan: dict, state: FridgeMateState) -> list[dict]:
    recipes = []
    for day in plan["days"]:
        for meal in day["meals"]:
            recipes.extend(retrieve_recipes(meal["name"], state))
    return recipes


def meal_agent(state: FridgeMateState) -> FridgeMateState:
    pantry_items = state.get("pantry_items") or parse_pantry_items(state.get("user_input", ""))
    state["pantry_items"] = pantry_items

    plan = create_weekly_plan(state)
    recipes = execute_meal_plan(plan, state)
    nutrition_check = verify_nutrition_goal(recipes, state.get("nutrition_goal", {}))

    return {
        **state,
        "meal_plan": plan,
        "selected_recipes": recipes,
        "logs": state.get("logs", [])
        + [
            {
                "node": "meal",
                "event": "plan_created",
                "prompt": MEAL_PLAN_PROMPT,
            },
            {
                "node": "meal",
                "event": "plan_executed",
                "prompt": MEAL_EXECUTE_PROMPT,
            },
            {
                "node": "meal",
                "event": "nutrition_verified",
                "result": nutrition_check,
            },
        ],
    }
