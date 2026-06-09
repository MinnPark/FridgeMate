"""classic ChatRequest ↔ v3 그래프 어댑터.

목적: 운영 엔드포인트(/chat, /chat/tool)와 프론트(chatAdapter.ts)를 건드리지 않고
v3 그래프(app/v3/graph.py)를 /chat/v3 로 붙이기 위한 양방향 변환 계층.

- chat_request_to_v3_state: classic ChatRequest(dict 형태) → v3 FridgeMateState 입력
- v3_state_to_chat_state:   v3 종료 state → 프론트가 이미 소비하는 ChatState(snake)

설계 메모: v3 노드/도구/RAG/시드는 그대로 재사용한다. 이 파일은 *순수 추가*이며
classic 경로를 일절 수정하지 않는다(롤백 = 이 모듈 + /chat/v3 제거).
"""
from __future__ import annotations

import uuid
from typing import Any

# ── mode → 끼니 스케줄 매핑 ──────────────────────────────────────────────────
# meal_plan_composer._build_slots 가 schedule.days × schedule.meals 로 슬롯을 만든다.
# 빈 schedule 이면 단일 끼니(오늘·저녁). 과다 생성 방지로 끼니 수를 보수적으로 둔다.
_MODE_SCHEDULE: dict[str, dict[str, list[str]]] = {
    "today":    {},  # → 1슬롯
    "weekend":  {"days": ["토", "일"], "meals": ["점심", "저녁"]},          # 4슬롯
    "mealprep": {"days": ["1일차", "2일차", "3일차"], "meals": ["점심", "저녁"]},  # 6슬롯
    "goal":     {"days": ["1일차", "2일차", "3일차"], "meals": ["저녁"]},    # 3슬롯
}


def _split_csv(text: str | None) -> list[str]:
    if not text:
        return []
    return [t.strip() for t in text.split(",") if t.strip()]


# ── (1) 입력 어댑터 ──────────────────────────────────────────────────────────
def chat_request_to_v3_state(req: dict[str, Any]) -> dict[str, Any]:
    """classic ChatRequest(model_dump dict) → v3 FridgeMateState 초기 입력.

    req 키(=main.ChatRequest): message, budget_limit, ingredient_entries[],
    excluded_ingredients, mode, protein_target_gram, calorie_target_kcal,
    carbs_target_gram, fat_target_gram, people.
    """
    message = (req.get("message") or "").strip()
    entries = req.get("ingredient_entries") or []

    # fridge_items: 구조화 입력(name) 우선. 없으면 ingredients(쉼표 문자열)에서 폴백.
    # (classic /chat/tool 은 message 기반이라 구조화 입력 없이도 동작했음 — 회귀 방지.)
    fridge_items = [e["name"] for e in entries if e.get("name")]
    if not fridge_items:
        fridge_items = _split_csv(req.get("ingredients"))

    nutrient_targets = {
        "kcal":    int(req.get("calorie_target_kcal") or 0),
        "protein": int(req.get("protein_target_gram") or 0),
        "carb":    int(req.get("carbs_target_gram") or 0),
        "fat":     int(req.get("fat_target_gram") or 0),
    }

    mode = req.get("mode") or "today"
    schedule = dict(_MODE_SCHEDULE.get(mode, {}))

    constraints: dict[str, Any] = {}
    excluded = _split_csv(req.get("excluded_ingredients"))
    if excluded:
        constraints["exclude"] = excluded

    thread_id = str(uuid.uuid4())
    return {
        "user_id":   "web",
        "thread_id": thread_id,
        "fridge_items": fridge_items,
        "intake_text": message,           # intake_node 가 선호/식이/스케줄 파싱
        "dish_goals": [],
        "diet_goals": [],
        "nutrient_targets": nutrient_targets,
        "budget":  int(req.get("budget_limit") or 0),
        "people":  max(int(req.get("people") or 1), 1),
        "constraints": constraints,
        "schedule": schedule,
    }


# ── (2) 출력 어댑터 ──────────────────────────────────────────────────────────
def _map_pantry_items(pantry: list[dict]) -> list[dict]:
    items = []
    for p in pantry:
        items.append({
            "name": p.get("name", ""),
            "amount": p.get("qty"),
            "unit": p.get("unit") or "",
            # v3 priority: 1=임박 가정. 현재 pantry_node 는 2(normal) 고정.
            "expiry_priority": "high" if p.get("priority") == 1 else "normal",
        })
    return items


def _map_pantry_analysis(pantry: list[dict]) -> dict:
    items = []
    priority_use: list[str] = []
    for p in pantry:
        name = p.get("name", "")
        qty, unit = p.get("qty"), p.get("unit") or ""
        is_high = p.get("priority") == 1
        if is_high:
            priority_use.append(name)
        items.append({
            "name": name,
            "category": "재료",
            "freshness": "soon" if is_high else "fresh",
            "amount": f"{qty}{unit}" if qty is not None else None,
            "expiry_label": None,
            "note": None,
        })
    summary = (
        f"냉장고 재료 {len(items)}개를 분석했어요."
        if items else "재료 정보가 없습니다."
    )
    return {"items": items, "priority_use": priority_use, "summary": summary}


def _map_selected_recipes(recipes: list[dict]) -> list[dict]:
    out = []
    for r in recipes:
        cit = r.get("citation") or {}
        rid = cit.get("id") or r.get("dish_name") or ""
        out.append({
            "id": str(rid),
            "name": r.get("dish_name", ""),
            "text": " ".join(r.get("steps") or []),
            "ingredients": [
                {"name": i.get("name", ""), "amount": i.get("qty"), "unit": i.get("unit") or ""}
                for i in (r.get("ingredients") or [])
            ],
            "nutrition": {
                "calories": r.get("calories", 0) or 0,
                "protein":  r.get("protein", 0) or 0,
                "carbs":    r.get("carb", 0) or 0,   # v3 carb → 프론트 carbs
                "fat":      r.get("fat", 0) or 0,
            },
        })
    return out


def _map_meal_plan(meal_plan: list[dict], suggestion: str) -> dict:
    """v3 meal_plan(list[MealSlot]) → 프론트 신형식 {note, days:[{label, entries}]}."""
    days_map: dict[str, list[dict]] = {}
    order: list[str] = []
    for slot in meal_plan:
        day = slot.get("day") or "오늘"
        if day not in days_map:
            days_map[day] = []
            order.append(day)
        days_map[day].append({
            "slot": slot.get("meal_type") or "저녁",      # 이미 한국어
            "recipeTitle": slot.get("dish_name", ""),
            "usesPriorityItem": (slot.get("pantry_coverage") or 0) > 0,
        })
    days = [{"label": d, "entries": days_map[d]} for d in order]
    return {"note": suggestion or None, "days": days}


def _map_nutrition_result(recipes: list[dict], targets: dict, judge: dict) -> dict:
    total = {"calories": 0.0, "protein": 0.0, "carb": 0.0, "fat": 0.0}
    for r in recipes:
        total["calories"] += r.get("calories", 0) or 0
        total["protein"]  += r.get("protein", 0) or 0
        total["carb"]     += r.get("carb", 0) or 0
        total["fat"]      += r.get("fat", 0) or 0
    return {
        "protein":  {"current": round(total["protein"]),  "target": targets.get("protein", 0), "unit": "g"},
        "calories": {"current": round(total["calories"]), "target": targets.get("kcal", 0),    "unit": "kcal"},
        "carbs":    {"current": round(total["carb"]),     "target": targets.get("carb", 0),    "unit": "g"},
        "fat":      {"current": round(total["fat"]),      "target": targets.get("fat", 0),     "unit": "g"},
        "passed":   bool(judge.get("pass", False)),
        "message":  judge.get("suggestion") or "",
        "warnings": judge.get("issues") or [],
    }


def _map_missing(missing: list[dict]) -> list[dict]:
    return [
        {
            "name": m.get("name", ""),
            "amount": m.get("shortage_qty"),
            "unit": m.get("unit") or "",
            "needed_by": m.get("used_in") or [],
        }
        for m in missing
    ]


def v3_state_to_chat_state(state: dict[str, Any], req: dict[str, Any]) -> dict[str, Any]:
    """v3 종료 state → 프론트(chatAdapter.ts)가 소비하는 ChatState(snake)."""
    pantry = state.get("pantry") or []
    recipes = state.get("recipes") or []
    meal_plan = state.get("meal_plan") or []
    missing = state.get("missing_ingredients") or []
    judge = state.get("judge_result") or {}
    targets = state.get("nutrient_targets") or {}
    suggestion = judge.get("suggestion") or ""

    # today 모드 = "오늘 냉장고 재료만, 장보기 불필요" → 부족재료/장보기 숨김 (classic /chat/tool 정책과 동일).
    if (req.get("mode") or "today") == "today":
        missing = []

    selected_recipes = _map_selected_recipes(recipes)

    # 프론트 AgentPipelinePanel 상태용 합성 로그 (node/event 키 필수)
    logs = [
        {"node": "pantry", "event": "pantry_analysis_completed",
         "result": {"total_items": len(pantry)}},
        {"node": "recipe", "event": "rag_retrieval_completed",
         "result": {"strategy": "v3-RAG", "recipes_found": len(selected_recipes)}},
        {"node": "meal", "event": "meal_plan_composed",
         "result": {"dishes_in_plan": len(meal_plan)}},
        {"node": "shopping", "event": "missing_calculated",
         "result": {"missing_count": len(missing)}},
    ]

    return {
        "user_input": req.get("message"),
        "budget_limit": req.get("budget_limit"),
        "pantry_items": _map_pantry_items(pantry),
        "pantry_analysis": _map_pantry_analysis(pantry),
        "selected_recipes": selected_recipes,
        "recipe_search_trace": {"strategy": "v3-RAG", "original_query": req.get("message", "")},
        "meal_plan": _map_meal_plan(meal_plan, suggestion),
        "nutrition_result": _map_nutrition_result(recipes, targets, judge),
        "missing_ingredients": _map_missing(missing),
        "logs": logs,
        "final_response": suggestion,
        # ── 디버깅/후속 단계용 패스스루 (프론트는 무시) ──
        "judge_result": judge,
        "shopping_candidates": state.get("shopping_candidates") or [],
        "cart_result": state.get("cart_result") or {},
        "kpi_log": state.get("kpi_log") or {},
        "errors": state.get("errors") or [],
        "reflexion_count": state.get("reflexion_count", 0),
    }
