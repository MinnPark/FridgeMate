from app.graph import orchestrator


def test_fallback_starts_with_recipe_when_recipes_are_missing():
    state = {
        "user_input": "냉장고 재료로 고단백 식단 짜줘",
        "pantry_items": [{"name": "두부"}],
    }

    assert orchestrator._fallback_route(state) == "recipe"


def test_supervisor_prevents_meal_before_recipe(monkeypatch):
    monkeypatch.setattr(
        orchestrator,
        "generate_json",
        lambda **_: {
            "route": "meal",
            "reason": "식단 요청",
            "next_steps": ["Meal Agent"],
        },
    )
    state = {
        "user_input": "고단백 식단 짜줘",
        "pantry_items": [{"name": "두부"}],
        "logs": [],
    }

    route = orchestrator.supervisor_router(state)

    assert route == "recipe"
    assert state["logs"][-1]["route"] == "recipe"


def test_graph_runs_recipe_before_meal_and_shopping(monkeypatch):
    def pantry(state):
        return {
            **state,
            "pantry_items": [{"name": "두부"}],
            "logs": [{"node": "pantry"}],
        }

    def recipe(state):
        return {
            **state,
            "selected_recipes": [{"name": "두부 된장찌개"}],
            "logs": [*state["logs"], {"node": "recipe"}],
        }

    def meal(state):
        return {
            **state,
            "meal_plan": {"days": []},
            "logs": [*state["logs"], {"node": "meal"}],
        }

    def shopping(state):
        return {
            **state,
            "cart_items": [],
            "logs": [*state["logs"], {"node": "shopping"}],
        }

    monkeypatch.setattr(orchestrator, "pantry_agent", pantry)
    monkeypatch.setattr(orchestrator, "recipe_agent", recipe)
    monkeypatch.setattr(orchestrator, "meal_agent", meal)
    monkeypatch.setattr(orchestrator, "shopping_agent", shopping)
    monkeypatch.setattr(
        orchestrator,
        "generate_json",
        lambda **_: {
            "route": "meal",
            "reason": "식단 요청",
            "next_steps": ["Meal Agent"],
        },
    )

    result = orchestrator.build_graph().invoke(
        {"user_input": "두부로 식단 짜줘", "logs": []},
    )

    assert [log["node"] for log in result["logs"] if "node" in log] == [
        "pantry",
        "recipe",
        "meal",
        "shopping",
    ]
