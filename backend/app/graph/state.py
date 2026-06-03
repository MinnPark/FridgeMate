from typing import Any, Literal, TypedDict


Route = Literal["meal", "shopping", "recipe", "finish"]


class FridgeMateState(TypedDict, total=False):
    user_input: str

    pantry_items: list[dict[str, Any]]
    nutrition_goal: dict[str, Any]

    meal_plan: dict[str, Any]
    selected_recipes: list[dict[str, Any]]
    recipe_search_trace: dict[str, Any]

    missing_ingredients: list[dict[str, Any]]
    cart_items: list[dict[str, Any]]
    budget_limit: int | None

    route: Route
    retry_count: int
    reflection: str | None

    logs: list[dict[str, Any]]
    final_response: str
