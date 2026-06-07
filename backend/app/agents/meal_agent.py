from app.agents.recipe_agent import retrieve_recipes
from app.graph.state import FridgeMateState
from app.llm import generate_json
from app.prompts.meal_prompts import MEAL_PLAN_PROMPT
from app.tools.logging_tools import append_log
from app.tools.nutrition_tools import verify_nutrition_goal
from app.tools.pantry_tools import parse_pantry_items


# ─────────────────────────────────────────────────────────────
# STEP 2: 칼로리 기준 슬롯 분류
# ─────────────────────────────────────────────────────────────
def _sort_recipes_by_slot(
    recipes: list[dict],
) -> tuple[list[str], list[str], list[str]]:
    """
    9개 레시피를 칼로리 기준으로 아침/점심/저녁 슬롯으로 분류

    반환:
      morning_titles  → 칼로리 낮은 순 (아침)
      lunch_titles    → 칼로리 높은 순 (점심)
      dinner_titles   → 칼로리 중간    (저녁)

    엣지케이스:
      nutrition 없는 레시피 → calories=0 으로 간주 → 아침 슬롯 우선
      recipes 빈 리스트     → ([], [], []) 반환
    """
    if not recipes:
        return [], [], []

    def get_calories(recipe: dict) -> float:
        nutrition = recipe.get("nutrition") or {}
        return float(nutrition.get("calories") or 0)

    sorted_recipes = sorted(recipes, key=get_calories)
    n     = len(sorted_recipes)
    chunk = max(1, n // 3)

    morning = sorted_recipes[:chunk]            # 하위 (낮은 칼로리)
    lunch   = sorted_recipes[n - chunk:]        # 상위 (높은 칼로리)
    dinner  = sorted_recipes[chunk: n - chunk]  # 중간

    return (
        [r.get("name", "") for r in morning],
        [r.get("name", "") for r in lunch],
        [r.get("name", "") for r in dinner],
    )


# ─────────────────────────────────────────────────────────────
# STEP 3: 칼로리 기준 후처리 보정
# ─────────────────────────────────────────────────────────────
def _apply_slot_calories(
    plan: dict,
    morning: list[str],
    lunch: list[str],
    dinner: list[str],
) -> dict:
    if not morning and not lunch and not dinner:
        return plan

    morning_set = set(morning)
    lunch_set   = set(lunch)

    all_entries = [
        entry
        for day in plan.get("days", [])
        for entry in day.get("entries", [])
    ]

    for i, entry in enumerate(all_entries):
        if entry.get("usesPriorityItem"):
            continue

        slot  = entry.get("slot", "")
        title = entry.get("recipeTitle", "")

        if slot == "아침" and title in lunch_set:
            for other in all_entries:
                if other is entry:
                    continue
                if other.get("usesPriorityItem"):
                    continue
                other_title = other.get("recipeTitle", "")
                if other.get("slot") != "아침" and other_title in morning_set:
                    entry["recipeTitle"] = other_title
                    other["recipeTitle"] = title
                    break

        elif slot == "점심" and title in morning_set:
            for other in all_entries:
                if other is entry:
                    continue
                if other.get("usesPriorityItem"):
                    continue
                other_title = other.get("recipeTitle", "")
                if other.get("slot") != "점심" and other_title in lunch_set:
                    entry["recipeTitle"] = other_title
                    other["recipeTitle"] = title
                    break

    return plan


# ─────────────────────────────────────────────────────────────
# 기존 _constrain_recipe_titles → _ensure_unique_recipes 교체
# ─────────────────────────────────────────────────────────────
def _ensure_unique_recipes(plan: dict, recipe_titles: list[str]) -> dict:
    """
    9개 레시피를 9개 슬롯에 1:1 배치 보장

    처리 순서:
      1. 허용 목록 벗어난 recipeTitle → 미사용 레시피로 교체
      2. 중복 recipeTitle              → 미사용 레시피로 교체
      3. 미사용 레시피 소진 시          → 허용 목록 순환 (안전장치)
    """
    if not recipe_titles:
        return plan

    allowed = set(recipe_titles)
    used    = set()
    unused  = list(recipe_titles)

    for day in plan.get("days", []):
        for entry in day.get("entries", []):
            title = entry.get("recipeTitle")

            # 허용 목록에 있고 아직 사용 안 했으면 그대로 사용
            if title in allowed and title not in used:
                used.add(title)
                if title in unused:
                    unused.remove(title)
                continue

            # 허용 목록 밖이거나 중복 → 미사용 레시피로 교체
            if unused:
                replacement = unused.pop(0)
                entry["recipeTitle"] = replacement
                used.add(replacement)
            else:
                # 미사용 소진 시 순환 (9개 초과 슬롯 안전장치)
                entry["recipeTitle"] = recipe_titles[len(used) % len(recipe_titles)]

    return plan


# ─────────────────────────────────────────────────────────────
# STEP 4: create_weekly_plan() 수정
# ─────────────────────────────────────────────────────────────
def create_weekly_plan(state: FridgeMateState) -> dict:
    """
    LLM을 사용해 3일 meal prep 식단 계획 생성. (LLM 1회 호출)

    입력:
      state["pantry_items"]       → 재료 + expiry_priority
      state["selected_recipes"]   → recipe_agent가 검색한 레시피 목록 (최대 9개)
      state["nutrition_goal"]     → 영양 목표

    출력:
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

    priority_items = [
        item["name"] for item in pantry_items
        if item.get("expiry_priority") == "high"
    ]
    recipe_titles = [r.get("name", "") for r in selected_recipes]

    # ── 칼로리 기준 슬롯 분류 ────────────────────────────────
    morning_titles, lunch_titles, dinner_titles = _sort_recipes_by_slot(selected_recipes)

    # ── fallback: index 0~8 순서대로 1:1 배치 ────────────────
    def recipe_at(index: int, default: str) -> str:
        if index < len(recipe_titles):
            return recipe_titles[index]
        return default

    fallback = {
        "note": "임박 재료를 앞쪽 일자에 배치했어요.",
        "days": [
            {
                "label": "1일차",
                "entries": [
                    {"slot": "아침", "recipeTitle": recipe_at(0, "레시피1"), "usesPriorityItem": True},
                    {"slot": "점심", "recipeTitle": recipe_at(1, "레시피2"), "usesPriorityItem": True},
                    {"slot": "저녁", "recipeTitle": recipe_at(2, "레시피3"), "usesPriorityItem": True},
                ],
            },
            {
                "label": "2일차",
                "entries": [
                    {"slot": "아침", "recipeTitle": recipe_at(3, "레시피4"), "usesPriorityItem": False},
                    {"slot": "점심", "recipeTitle": recipe_at(4, "레시피5"), "usesPriorityItem": False},
                    {"slot": "저녁", "recipeTitle": recipe_at(5, "레시피6"), "usesPriorityItem": False},
                ],
            },
            {
                "label": "3일차",
                "entries": [
                    {"slot": "아침", "recipeTitle": recipe_at(6, "레시피7"), "usesPriorityItem": False},
                    {"slot": "점심", "recipeTitle": recipe_at(7, "레시피8"), "usesPriorityItem": False},
                    {"slot": "저녁", "recipeTitle": recipe_at(8, "레시피9"), "usesPriorityItem": False},
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
            f"아침 슬롯 추천 레시피(칼로리 낮은 순): {morning_titles}\n"
            f"점심 슬롯 추천 레시피(칼로리 높은 순): {lunch_titles}\n"
            f"저녁 슬롯 추천 레시피(칼로리 중간):   {dinner_titles}\n"
            "위 재료와 레시피를 활용해 3일 meal prep 식단 계획을 JSON으로 작성하세요.\n"
            "⚠️ 규칙: 9개 레시피를 3일 × 3끼 = 9개 슬롯에 각각 1번씩만 배치하세요. 중복 사용 금지."
        ),
        fallback=fallback,
    )

    plan.setdefault("note", fallback["note"])
    plan.setdefault("days", fallback["days"])

    # 후처리 순서 중요: unique → priority → calories
    plan = _ensure_unique_recipes(plan, recipe_titles)          # 1. 중복 제거
    plan = _mark_priority_items(plan, pantry_items)             # 2. priority 보정
    plan = _apply_slot_calories(                                # 3. 칼로리 보정
        plan, morning_titles, lunch_titles, dinner_titles
    )

    return plan


def _mark_priority_items(plan: dict, pantry_items: list[dict]) -> dict:
    """
    recipeTitle에 priority(high) 재료 이름이 포함된 끼니는
    usesPriorityItem: true 자동 설정.
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
    출력:  state["meal_plan"]
           state["nutrition_result"]
           state["selected_recipes"]   (recipe_agent 결과 그대로 유지)
           state["logs"]
    """
    pantry_items = state.get("pantry_items") or parse_pantry_items(state.get("user_input", ""))
    state["pantry_items"] = pantry_items

    plan = create_weekly_plan(state)

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
        "selected_recipes": selected_recipes,
        "nutrition_result": nutrition_check,
        "logs":             logs,
    }


def _extract_constraints(user_input: str) -> list[str]:
    """user_input에서 제약 조건 키워드 추출."""
    constraints = []
    for token in ["고단백", "저칼로리", "저탄수", "한식", "예산", "주간", "간단"]:
        if token in user_input:
            constraints.append(token)
    return constraints


def _summarize_plan(plan: dict) -> dict:
    """로그용 plan 요약"""
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
