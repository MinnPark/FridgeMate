from app.graph.state import FridgeMateState
from app.tools.pantry_tools import build_pantry_analysis, build_pantry_items


def pantry_agent(state: FridgeMateState) -> FridgeMateState:
    """
    입력:  state["ingredient_entries"]  (프론트에서 구조화된 재료 목록)
    출력:  state["pantry_items"]        (다른 agent용)
           state["pantry_analysis"]     (UI PantryCard용)
           state["logs"]                (파이프라인 추적용)
    """
    entries = state.get("ingredient_entries") or []

    # ingredient_entries가 없으면 빈 상태로 진행
    if not entries:
        return {
            **state,
            "pantry_items": [],
            "pantry_analysis": {
                "items": [],
                "priority_use": [],
                "summary": "재료 정보가 없습니다.",
            },
            "logs": [
                *(state.get("logs") or []),
                {
                    "node": "pantry",
                    "event": "skipped",
                    "reason": "ingredient_entries 없음",
                },
            ],
        }

    # 1. pantry_items 생성 (다른 agent용)
    pantry_items = build_pantry_items(entries)

    # 2. pantry_analysis 생성 (UI PantryCard용)
    pantry_analysis = build_pantry_analysis(pantry_items)

    # 3. 로그
    logs = [
        *(state.get("logs") or []),
        {
            "node": "pantry",
            "event": "pantry_analysis_completed",
            "result": {
                "total_items": len(pantry_items),
                "priority_items": pantry_analysis["priority_use"],
                "summary": pantry_analysis["summary"],
            },
        },
    ]

    return {
        **state,
        "pantry_items": pantry_items,
        "pantry_analysis": pantry_analysis,
        "logs": logs,
    }