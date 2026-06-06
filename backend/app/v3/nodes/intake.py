"""Intake 노드 — v3 (선호도 · 요리목표 · 라이프스타일 패턴 · 영양 파싱).

구 desire_capture 확장. 진입 후 두 번째 노드.
  - 휴리스틱: 키워드/정규식 (offline, 즉시 동작)
  - LLM: FRIDGEMATE_USE_LLM=true + 키 있을 때 intake 프롬프트로 구조화 (cache_control)
        실패 시 휴리스틱 폴백.
구조화 입력(preferences/dish_goals/schedule)이 이미 들어왔으면 보존하고, intake_text 로
들어온 자연어만 파싱해서 병합한다. 아무것도 없으면 그냥 통과 — composer 가 중립 처리.
"""
from __future__ import annotations

import json
import re

from app.v3.state import FridgeMateState, Preferences, Schedule
from app.rag._llm import call_llm, llm_enabled

CUISINE_KEYWORDS = {
    "한식": ["한식", "한국"],
    "양식": ["양식", "이태리", "파스타", "피자", "스테이크"],
    "일식": ["일식", "초밥", "라멘", "덮밥", "우동"],
    "중식": ["중식", "짜장", "마파", "탕수"],
}

DAY_KEYWORDS = {
    "주말": ["토", "일"],
    "주중": ["주중"],
    "평일": ["주중"],
}

MEAL_KEYWORDS = ["아침", "점심", "저녁", "야식", "브런치"]
DIET_KEYWORDS = {
    "고단백": ["고단백", "단백질", "벌크업", "근육"],
    "저칼로리": ["저칼로리", "다이어트", "살 빼", "감량"],
    "저탄수": ["저탄수", "키토", "탄수 줄"],
}


def _heuristic_parse(text: str, base_prefs: Preferences, base_sched: Schedule) -> tuple[Preferences, list[str], Schedule, list[str]]:
    prefs: Preferences = dict(base_prefs)  # type: ignore[assignment]
    sched: Schedule = dict(base_sched)     # type: ignore[assignment]
    diet_goals: list[str] = []
    dish_goals: list[str] = []

    if not text or not text.strip():
        return prefs, dish_goals, sched, diet_goals

    cuisines = list(prefs.get("cuisines") or [])
    for cuisine, keys in CUISINE_KEYWORDS.items():
        if any(k in text for k in keys) and cuisine not in cuisines:
            cuisines.append(cuisine)
    if cuisines:
        prefs["cuisines"] = cuisines

    if any(k in text for k in ["매콤", "매운", "맵"]):
        prefs["spice_level"] = 2
    elif any(k in text for k in ["안 맵", "순한", "안맵"]):
        prefs["spice_level"] = 0

    # dislikes: "X 빼" / "X 싫" / "X 말고"
    dislikes = list(prefs.get("dislikes") or [])
    for m in re.finditer(r"([가-힣]{2,6})\s*(?:빼|싫|말고|제외)", text):
        token = m.group(1)
        if token not in dislikes:
            dislikes.append(token)
    if dislikes:
        prefs["dislikes"] = dislikes

    # schedule: 주말/주중 + 끼니
    days = list(sched.get("days") or [])
    for kw, mapped in DAY_KEYWORDS.items():
        if kw in text:
            for d in mapped:
                if d not in days:
                    days.append(d)
    if days:
        sched["days"] = days
    meals = list(sched.get("meals") or [])
    for m in MEAL_KEYWORDS:
        if m in text and m not in meals:
            meals.append(m)
    if meals:
        sched["meals"] = meals

    for label, keys in DIET_KEYWORDS.items():
        if any(k in text for k in keys):
            diet_goals.append(label)

    return prefs, dish_goals, sched, diet_goals


async def _llm_parse(text: str) -> dict | None:
    raw = await call_llm(
        system_prompt_name="intake",
        user_content=text,
        model_env="ANTHROPIC_MODEL_DEFAULT",
        fallback="",
        max_tokens=400,
    )
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


async def intake_node(state: FridgeMateState) -> dict:
    text = (state.get("intake_text") or "").strip()
    base_prefs: Preferences = state.get("preferences") or {}  # type: ignore[assignment]
    base_sched: Schedule = state.get("schedule") or {}        # type: ignore[assignment]
    existing_goals = list(state.get("dish_goals") or [])
    existing_diet = list(state.get("diet_goals") or [])

    prefs, dish_goals, sched, diet_goals = _heuristic_parse(text, base_prefs, base_sched)

    if text and llm_enabled():
        data = await _llm_parse(text)
        if data:
            if isinstance(data.get("cuisines"), list) and data["cuisines"]:
                prefs["cuisines"] = list({*(prefs.get("cuisines") or []), *data["cuisines"]})
            if isinstance(data.get("spice_level"), int):
                prefs["spice_level"] = data["spice_level"]
            if isinstance(data.get("dislikes"), list) and data["dislikes"]:
                prefs["dislikes"] = list({*(prefs.get("dislikes") or []), *data["dislikes"]})
            if isinstance(data.get("favorites"), list) and data["favorites"]:
                prefs["favorites"] = list({*(prefs.get("favorites") or []), *data["favorites"]})
            if isinstance(data.get("dish_goals"), list):
                dish_goals = data["dish_goals"]
            sch = data.get("schedule") or {}
            if isinstance(sch.get("days"), list) and sch["days"]:
                sched["days"] = sch["days"]
            if isinstance(sch.get("meals"), list) and sch["meals"]:
                sched["meals"] = sch["meals"]
            if isinstance(data.get("diet_goals"), list) and data["diet_goals"]:
                diet_goals = data["diet_goals"]

    return {
        "preferences": prefs,
        "dish_goals": list({*existing_goals, *dish_goals}) if (existing_goals or dish_goals) else existing_goals,
        "schedule": sched,
        "diet_goals": list({*existing_diet, *diet_goals}) if (existing_diet or diet_goals) else existing_diet,
    }
