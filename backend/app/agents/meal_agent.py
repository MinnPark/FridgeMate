from app.agents.recipe_agent import retrieve_recipes
from app.graph.state import FridgeMateState
from app.llm import generate_json
from app.prompts.meal_prompts import MEAL_EXECUTE_PROMPT, MEAL_PLAN_PROMPT
from app.tools.logging_tools import append_log
from app.tools.nutrition_tools import verify_nutrition_goal
from app.tools.pantry_tools import parse_pantry_items


def create_weekly_plan(state: FridgeMateState) -> dict:
    pantry_items = state.get("pantry_items") or parse_pantry_items(state.get("user_input", ""))
    fallback = {
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
        "constraints": _extract_constraints(state.get("user_input", "")),
    }
    plan = generate_json(
        system_prompt=MEAL_PLAN_PROMPT,
        user_prompt=(
            f"사용자 요청: {state.get('user_input', '')}\n"
            f"냉장고 재료 JSON: {pantry_items}\n"
            f"영양 목표: {state.get('nutrition_goal', {})}\n"
            "냉장고 재료를 우선 사용하는 1일~3일 식단 계획을 JSON으로 작성하세요."
        ),
        fallback=fallback,
    )
    plan.setdefault("strategy", "Plan-and-Execute")
    plan.setdefault("days", fallback["days"])
    plan.setdefault("pantry_used_first", fallback["pantry_used_first"])
    return plan


def execute_meal_plan(plan: dict, state: FridgeMateState) -> tuple[list[dict], list[dict]]:
    recipes = []
    execution_trace = []
    seen_recipe_ids = set()

    for day in plan.get("days", []):
        for meal in day.get("meals", []):
            meal_name = meal.get("name", "")
            retrieved = retrieve_recipes(meal_name, state)
            added = []
            for recipe in retrieved:
                recipe_id = recipe.get("id", recipe.get("name"))
                if recipe_id in seen_recipe_ids:
                    continue
                recipes.append(recipe)
                added.append(recipe.get("name"))
                seen_recipe_ids.add(recipe_id)
            execution_trace.append(
                {
                    "meal": meal_name,
                    "action": "retrieve_recipes",
                    "observation": added,
                    "rag_trace": state.get("recipe_search_trace", {}),
                }
            )

    return recipes, execution_trace


def meal_agent(state: FridgeMateState) -> FridgeMateState:
    pantry_items = state.get("pantry_items") or parse_pantry_items(state.get("user_input", ""))
    state["pantry_items"] = pantry_items

    plan = create_weekly_plan(state)
    recipes, execution_trace = execute_meal_plan(plan, state)
    nutrition_check = verify_nutrition_goal(recipes, state.get("nutrition_goal", {}))

    logs = append_log(
        state.get("logs"),
        node="meal",
        event="plan_created",
        prompt=MEAL_PLAN_PROMPT,
        plan_summary=_summarize_plan(plan),
        llm=plan.get("_meta"),
    )
    logs = append_log(
        logs,
        node="meal",
        event="plan_executed",
        prompt=MEAL_EXECUTE_PROMPT,
        trace=execution_trace,
    )
    logs = append_log(
        logs,
        node="meal",
        event="nutrition_verified",
        result=nutrition_check,
    )

    return {
        **state,
        "meal_plan": plan,
        "selected_recipes": recipes,
        "logs": logs,
    }


def _extract_constraints(user_input: str) -> list[str]:
    constraints = []
    for token in ["고단백", "저칼로리", "저탄수", "한식", "예산", "주간", "간단"]:
        if token in user_input:
            constraints.append(token)
    return constraints


def _summarize_plan(plan: dict) -> dict:
    meals = [
        meal.get("name")
        for day in plan.get("days", [])
        for meal in day.get("meals", [])
    ]
    return {
        "strategy": plan.get("strategy"),
        "meal_count": len(meals),
        "meals": meals,
        "pantry_used_first": plan.get("pantry_used_first", []),
    }
