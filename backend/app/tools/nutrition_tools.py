from typing import Any


MOCK_NUTRITION_DB = {
    "두부": {"per": 100, "calories": 84, "protein": 9},
    "계란": {"per": 1, "calories": 70, "protein": 6},
    "닭가슴살": {"per": 100, "calories": 165, "protein": 23},
}


def query_nutrition_db(ingredient_name: str) -> dict[str, Any] | None:
    """Tool Calling target: replace with PostgreSQL lookup in production."""
    return MOCK_NUTRITION_DB.get(ingredient_name)


def verify_nutrition_goal(recipes: list[dict[str, Any]], goal: dict[str, Any]) -> dict[str, Any]:
    total = {"calories": 0, "protein": 0}
    for recipe in recipes:
        nutrition = recipe.get("nutrition", {})
        total["calories"] += nutrition.get("calories", 0)
        total["protein"] += nutrition.get("protein", 0)

    protein_goal = goal.get("protein_min", 40)
    return {
        "total": total,
        "goal": {"protein_min": protein_goal},
        "passed": total["protein"] >= protein_goal,
        "source": "tool_verified",
    }
