from app.agents.meal_agent import _constrain_recipe_titles


def test_meal_plan_only_uses_selected_recipe_titles():
    plan = {
        "days": [
            {
                "entries": [
                    {"slot": "아침", "recipeTitle": "목록 밖 레시피"},
                    {"slot": "점심", "recipeTitle": "두부 된장찌개"},
                ],
            },
        ],
    }

    result = _constrain_recipe_titles(
        plan,
        ["두부 된장찌개", "계란 볶음밥"],
    )

    assert [
        entry["recipeTitle"]
        for entry in result["days"][0]["entries"]
    ] == ["두부 된장찌개", "두부 된장찌개"]
