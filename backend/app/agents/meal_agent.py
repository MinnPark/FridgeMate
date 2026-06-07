from app.agents.recipe_agent import retrieve_recipes
from app.graph.state import FridgeMateState
from app.llm import generate_json
from app.prompts.meal_prompts import MEAL_PLAN_PROMPT
from app.tools.logging_tools import append_log
from app.tools.nutrition_tools import verify_nutrition_goal
from app.tools.pantry_tools import parse_pantry_items


def create_weekly_plan(state: FridgeMateState) -> dict:
    """
    LLM을 사용해 3일 meal prep 식단 계획 생성. (LLM 1회 호출)

    입력:
      state["pantry_items"]       → 재료 + expiry_priority
      state["selected_recipes"]   → recipe_agent가 검색한 레시피 목록
      state["nutrition_goal"]     → 영양 목표

    출력 (mock.ts mealPlan 계약 형태):
      {
        "note": "임박 재료를 앞쪽 일자에 배치했어요.",
        "days": [
          {
            "label": "1일차",
            "entries": [
              {"slot": "아침", "recipeTitle": "...", "usesPriorityItem": true}
            ]
          }
        ]
      }
    """
    pantry_items     = state.get("pantry_items") or []
    selected_recipes = state.get("selected_recipes") or []

    # priority_items: expiry_priority == "high" 재료 이름 목록
    priority_items = [
        item["name"] for item in pantry_items
        if item.get("expiry_priority") == "high"
    ]
    # recipe_agent가 검색한 레시피 이름 목록 → LLM에 전달
    recipe_titles = [r.get("name", "") for r in selected_recipes]

    def recipe_at(index: int, default: str) -> str:
        if recipe_titles:
            return recipe_titles[index % len(recipe_titles)]
        return default

    # LLM 실패 시 fallback (selected_recipes 기반으로 자동 구성)
    fallback = {
        "note": "임박 재료를 앞쪽 일자에 배치했어요.",
        "days": [
            {
                "label": "1일차",
                "entries": [
                    {"slot": "아침", "recipeTitle": recipe_at(1, "브로콜리 계란 스크램블"), "usesPriorityItem": True},
                    {"slot": "점심", "recipeTitle": recipe_at(0, "닭가슴살 두부 강된장 덮밥"), "usesPriorityItem": True},
                    {"slot": "저녁", "recipeTitle": recipe_at(2, "닭가슴살 두부 스테이크"), "usesPriorityItem": True},
                ],
            },
            {
                "label": "2일차",
                "entries": [
                    {"slot": "아침", "recipeTitle": recipe_at(0, "그릭요거트 + 방울토마토")},
                    {"slot": "점심", "recipeTitle": recipe_at(1, "닭가슴살 두부 강된장 덮밥")},
                    {"slot": "저녁", "recipeTitle": recipe_at(2, "브로콜리 계란 스크램블")},
                ],
            },
            {
                "label": "3일차",
                "entries": [
                    {"slot": "아침", "recipeTitle": recipe_at(2, "계란 현미 주먹밥")},
                    {"slot": "점심", "recipeTitle": recipe_at(0, "닭가슴살 두부 스테이크")},
                    {"slot": "저녁", "recipeTitle": recipe_at(1, "닭가슴살 채소 볶음")},
                ],
            },
        ],
    }

    plan = generate_json(
        system_prompt=MEAL_PLAN_PROMPT,
        user_prompt=(
            f"사용자 요청: {state.get('user_input', '')}\n"
            f"냉장고 재료: {[item['name'] for item in pantry_items]}\n"
            f"유통기한 임박 재료(priority_items): {priority_items}\n"
            f"선택된 레시피 목록(반드시 이 목록에서만 선택): {recipe_titles}\n"
            f"영양 목표: {state.get('nutrition_goal', {})}\n"
            "위 재료와 레시피를 활용해 3일 meal prep 식단 계획을 JSON으로 작성하세요."
        ),
        fallback=fallback,
    )

    # 필수 키 보정
    plan.setdefault("note", fallback["note"])
    plan.setdefault("days", fallback["days"])

    # Shopping Agent는 meal_plan의 recipeTitle을 selected_recipes와 이름으로 매핑한다.
    # LLM이 목록 밖 레시피를 만들면 재료 계산이 누락되므로 허용 목록으로 보정한다.
    plan = _constrain_recipe_titles(plan, recipe_titles)

    # usesPriorityItem 자동 보정 (LLM이 누락하거나 틀렸을 때 대비)
    plan = _mark_priority_items(plan, pantry_items)

    return plan


def _constrain_recipe_titles(plan: dict, recipe_titles: list[str]) -> dict:
    if not recipe_titles:
        return plan

    index = 0
    allowed = set(recipe_titles)
    for day in plan.get("days", []):
        for entry in day.get("entries", []):
            if entry.get("recipeTitle") not in allowed:
                entry["recipeTitle"] = recipe_titles[index % len(recipe_titles)]
            index += 1
    return plan


def _mark_priority_items(plan: dict, pantry_items: list[dict]) -> dict:
    """
    recipeTitle에 priority(high) 재료 이름이 포함된 끼니는
    usesPriorityItem: true 자동 설정.

    LLM이 usesPriorityItem을 누락하거나 잘못 표시한 경우 보정한다.
    """
    priority_names = [
        item["name"] for item in pantry_items
        if item.get("expiry_priority") == "high"
    ]
    if not priority_names:
        return plan

    for day in plan.get("days", []):
        for entry in day.get("entries", []):
            recipe_title = entry.get("recipeTitle", "")
            has_priority = any(name in recipe_title for name in priority_names)
            if has_priority:
                entry["usesPriorityItem"] = True
            else:
                entry.setdefault("usesPriorityItem", False)

    return plan


def meal_agent(state: FridgeMateState) -> FridgeMateState:
    """
    입력:  state["pantry_items"]       (pantry_agent 생성)
           state["selected_recipes"]   (recipe_agent 생성)
           state["nutrition_goal"]     (main.py ChatRequest)
    출력:  state["meal_plan"]          (UI MealPlanCard용)
           state["nutrition_result"]   (UI NutritionCard + chatAdapter.ts 매핑)
           state["selected_recipes"]   (recipe_agent 결과 그대로 유지 — 오염 없음)
           state["logs"]

    변경 사항:
      execute_meal_plan() 제거
        → RAG 9회 호출 제거 (문제 3 해결)
        → selected_recipes 오염 제거 (문제 2 해결)
      verify_nutrition_goal()는 recipe_agent의 selected_recipes만 사용
        → 일일 대표 레시피(3~5개) 영양 합산 = 일일 nutrition_goal과 직접 비교
    """
    pantry_items = state.get("pantry_items") or parse_pantry_items(state.get("user_input", ""))
    state["pantry_items"] = pantry_items

    # 1. 3일 meal prep 식단 계획 생성 (LLM 1회 호출)
    plan = create_weekly_plan(state)

    # 2. 영양 검증
    #    recipe_agent의 selected_recipes만 사용 (execute_meal_plan 제거)
    #    → selected_recipes = 이 식단의 대표 레시피 3~5개
    #    → 영양 합산 = 일일 섭취 기준과 직접 비교 가능
    selected_recipes = state.get("selected_recipes") or []
    nutrition_check = verify_nutrition_goal(
        selected_recipes,
        state.get("nutrition_goal") or {},
    )

    logs = append_log(
        state.get("logs"),
        node="meal",
        event="plan_created",
        prompt=MEAL_PLAN_PROMPT,
        plan_summary=_summarize_plan(plan),
    )
    logs = append_log(
        logs,
        node="meal",
        event="nutrition_verified",
        result=nutrition_check,
    )

    return {
        **state,
        "meal_plan":        plan,
        "selected_recipes": selected_recipes,   # recipe_agent 결과 그대로 유지
        "nutrition_result": nutrition_check,
        "logs":             logs,
    }


def _extract_constraints(user_input: str) -> list[str]:
    """user_input에서 제약 조건 키워드 추출. shopping_agent에서도 활용 가능."""
    constraints = []
    for token in ["고단백", "저칼로리", "저탄수", "한식", "예산", "주간", "간단"]:
        if token in user_input:
            constraints.append(token)
    return constraints


def _summarize_plan(plan: dict) -> dict:
    """로그용 plan 요약 — entries/recipeTitle 기준"""
    meals = [
        entry.get("recipeTitle")
        for day in plan.get("days", [])
        for entry in day.get("entries", [])
    ]
    return {
        "note":       plan.get("note"),
        "meal_count": len(meals),
        "meals":      meals,
    }
