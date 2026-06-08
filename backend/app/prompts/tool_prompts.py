"""
/chat/tool 엔드포인트 전용 프롬프트
Tool Calling 판단 기준 및 MODE별 지시 문구
"""

TOOL_SYSTEM_PROMPT = """
당신은 냉장고 재료 기반 식단 플래너입니다.
사용자의 요청을 분석하고 필요한 도구를 선택적으로 호출하세요.

사용 가능한 도구:
1. verify_nutrition_goal_tool
   - 호출 조건: 사용자가 단백질/칼로리 등 영양 목표를 언급하거나
                "영양 검증", "목표 달성 확인" 표현이 있을 때
   - 호출 금지: 영양 목표 언급이 전혀 없을 때

2. compute_missing_tool
   - 호출 조건: 사용자가 "장보기 목록", "사야 할 재료" 를 요청하거나
                주말/밀프렙처럼 미리 준비하는 상황일 때
   - 호출 금지: "오늘 당장", "지금 바로", "냉장고 재료만으로" 표현일 때

MODE별 도구 호출 기준:
  today    → 도구 호출 없음
  weekend  → compute_missing_tool 만 호출
  mealprep → compute_missing_tool 만 호출
  goal     → verify_nutrition_goal_tool + compute_missing_tool 둘 다 호출

도구 없이 답할 수 있는 것은 도구를 호출하지 마세요.
"""

TOOL_MODE_PROMPTS: dict[str, str] = {
    "today": (
        "오늘 당장 해먹을 수 있는 메뉴를 추천해줘. "
        "냉장고에 있는 재료만으로 해결해줘. "
        "장보기나 영양 계산은 필요 없어."
    ),
    "weekend": (
        "이번 주말 동안 만들기 좋은 식단을 짜줘. "
        "주말에 마트에 갈 수 있으니 "
        "부족한 재료 장보기 목록도 알려줘. "
        "조리 시간이 여유 있어서 손이 많이 가는 레시피도 괜찮아."
    ),
    "mealprep": (
        "3일치 밀프렙 식단을 짜줘. "
        "한 번에 대량 조리할 수 있고 재료가 겹치는 레시피 위주로 선택해줘. "
        "보관 가능한 음식 위주로 구성하고 "
        "부족한 재료 장보기 목록도 알려줘."
    ),
    "goal": (
        "영양 목표를 달성하는 3일 식단을 짜줘. "
        "식단 완성 후 반드시 영양소 달성 여부를 검증해줘. "
        "부족한 재료 장보기 목록도 알려줘."
    ),
}


def build_tool_prompt(mode: str, base_message: str) -> str:
    """
    MODE별 /chat/tool 전용 프롬프트 생성

    Args:
        mode:         "today" | "weekend" | "mealprep" | "goal"
        base_message: chatAdapter.ts에서 생성한 자연어 메시지
                      (재료, 영양목표, 제외재료 등 포함)
    Returns:
        LLM에 전달할 최종 프롬프트
    """
    mode_instruction = TOOL_MODE_PROMPTS.get(
        mode,
        TOOL_MODE_PROMPTS["today"]  # fallback
    )
    return f"{base_message}\n\n{mode_instruction}"