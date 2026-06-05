from typing import Any, Literal, TypedDict


Route = Literal["meal", "shopping", "recipe", "finish"]


class FridgeMateState(TypedDict, total=False):
    # 입력
    user_input: str
    ingredient_entries: list[dict[str, Any]]   # 프론트 구조화 입력

    # Pantry
    pantry_items: list[dict[str, Any]]
    pantry_analysis: dict[str, Any]            # UI PantryCard용

    # 영양
    nutrition_goal: dict[str, Any]

    # 레시피
    selected_recipes: list[dict[str, Any]]
    recipe_search_trace: dict[str, Any]

    # 식단
    meal_plan: dict[str, Any]

    # 장보기
    missing_ingredients: list[dict[str, Any]]
    cart_items: list[dict[str, Any]]
    budget_limit: int | None

    # 에이전트 내부 (API 응답에 포함 X)
    route: Route
    retry_count: int
    reflection: str | None

    # 공통
    logs: list[dict[str, Any]]
    final_response: str
