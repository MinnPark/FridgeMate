from typing import Any, Literal, TypedDict


Route = Literal["meal", "shopping", "recipe", "finish"]
Mode = Literal["today", "weekend", "mealprep", "goal"]   # ← 추가


class FridgeMateState(TypedDict, total=False):
    # 입력
    user_input: str
    ingredient_entries: list[dict[str, Any]]   # 프론트 구조화 입력
    excluded_ingredients: str                  # ← 추가 ("닭가슴살,돼지고기" 형식)
    mode: Mode                                             # ← 추가

    # Pantry
    pantry_items: list[dict[str, Any]]
    pantry_analysis: dict[str, Any]            # UI PantryCard용

    # 영양
    nutrition_goal: dict[str, Any]             # 입력: 목표값 (protein_target, calorie_target 등)
    nutrition_result: dict[str, Any]           # 출력: 검증 결과 → chatAdapter.ts nutrition 필드 매핑

    # 레시피
    selected_recipes: list[dict[str, Any]]
    recipe_search_trace: dict[str, Any]

    # 식단
    meal_plan: dict[str, Any]

    # 장보기
    missing_ingredients: list[dict]
    # 구조: [{"name": str, "amount": float|None, "unit": str|None, "needed_by": [str]}]
    cart_items: list[dict[str, Any]]
    budget_limit: int | None

    # 에이전트 내부 (API 응답에 포함 X)
    route: Route
    retry_count: int
    reflection: str | None

    # 공통
    logs: list[dict[str, Any]]
    final_response: str
