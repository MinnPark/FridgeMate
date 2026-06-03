from app.config import settings
from app.graph.state import FridgeMateState
from app.prompts.shopping_prompts import REACT_PROMPT, REFLEXION_PROMPT
from app.tools.shopping_tools import (
    calculate_missing_ingredients,
    create_cart_deeplinks,
    search_coupang_products,
    validate_budget,
)


def reflect_failure(reason: str, state: FridgeMateState) -> str:
    previous = state.get("reflection")
    if previous:
        return f"{previous} 이번 실패 원인: {reason}. 더 저렴한 대체 상품을 우선한다."
    return f"실패 원인: {reason}. 다음 루프에서는 소용량 또는 저가 상품을 우선 검색한다."


def shopping_agent(state: FridgeMateState) -> FridgeMateState:
    retry_count = state.get("retry_count", 0)
    missing = calculate_missing_ingredients(
        state.get("pantry_items", []),
        state.get("selected_recipes", []),
    )
    products = search_coupang_products(missing, reflection=state.get("reflection"))
    cart_items = create_cart_deeplinks(products)
    ok, reason = validate_budget(cart_items, state.get("budget_limit"))

    logs = state.get("logs", []) + [
        {
            "node": "shopping",
            "event": "react_loop_executed",
            "prompt": REACT_PROMPT,
            "retry_count": retry_count,
        }
    ]

    if ok:
        return {
            **state,
            "missing_ingredients": missing,
            "cart_items": cart_items,
            "logs": logs + [{"node": "shopping", "event": "cart_created"}],
            "final_response": "식단 추천, 부족 재료 계산, 쿠팡 장바구니 후보 생성을 완료했습니다.",
        }

    if retry_count >= settings.max_shopping_retries:
        return {
            **state,
            "missing_ingredients": missing,
            "cart_items": cart_items,
            "logs": logs
            + [
                {
                    "node": "shopping",
                    "event": "user_approval_required",
                    "reason": reason,
                }
            ],
            "final_response": "예산 조건을 만족하지 못해 사용자 승인이 필요합니다.",
        }

    reflection = reflect_failure(reason or "unknown failure", state)
    return shopping_agent(
        {
            **state,
            "retry_count": retry_count + 1,
            "reflection": reflection,
            "logs": logs
            + [
                {
                    "node": "shopping",
                    "event": "reflexion_generated",
                    "prompt": REFLEXION_PROMPT,
                    "reflection": reflection,
                }
            ],
        }
    )
