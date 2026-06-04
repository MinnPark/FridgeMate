from app.config import settings
from app.graph.state import FridgeMateState
from app.llm import generate_json
from app.prompts.shopping_prompts import REACT_PROMPT, REFLEXION_PROMPT
from app.tools.logging_tools import append_log
from app.tools.shopping_tools import (
    calculate_missing_ingredients,
    create_cart_deeplinks,
    search_coupang_products,
    validate_budget,
)


def reflect_failure(reason: str, state: FridgeMateState) -> str:
    previous = state.get("reflection")
    fallback = {
        "reflection": (
            f"{previous + ' ' if previous else ''}"
            f"실패 원인: {reason}. 다음 루프에서는 소용량 또는 저가 상품을 우선 검색한다."
        ),
        "changed_strategy": "budget_first_small_pack",
    }
    result = generate_json(
        system_prompt=REFLEXION_PROMPT,
        user_prompt=(
            f"사용자 요청: {state.get('user_input', '')}\n"
            f"예산: {state.get('budget_limit')}\n"
            f"이전 실패 원인: {reason}\n"
            f"이전 회고: {previous}\n"
            "다음 쇼핑 루프에서 반복하지 말아야 할 실수와 바뀐 전략을 JSON으로 작성하세요."
        ),
        fallback=fallback,
    )
    return result.get("reflection", fallback["reflection"])


def shopping_agent(state: FridgeMateState) -> FridgeMateState:
    missing = calculate_missing_ingredients(
        state.get("pantry_items", []),
        state.get("selected_recipes", []),
    )
    logs = append_log(
        state.get("logs"),
        node="shopping",
        event="react_started",
        prompt=REACT_PROMPT,
        missing_ingredients=missing,
    )

    reflection = state.get("reflection")
    final_cart_items = []
    final_reason = None

    for retry_count in range(state.get("retry_count", 0), settings.max_shopping_retries + 1):
        thought = _build_thought(missing, state.get("budget_limit"), retry_count, reflection)
        logs = append_log(
            logs,
            node="shopping",
            event="react_thought",
            retry_count=retry_count,
            thought=thought,
        )

        products = search_coupang_products(missing, reflection=reflection)
        logs = append_log(
            logs,
            node="shopping",
            event="react_action",
            retry_count=retry_count,
            action="search_coupang_products",
            tool_input={"missing_ingredients": missing, "reflection": reflection},
        )

        cart_items = create_cart_deeplinks(products)
        ok, reason = validate_budget(cart_items, state.get("budget_limit"))
        final_cart_items = cart_items
        final_reason = reason
        logs = append_log(
            logs,
            node="shopping",
            event="react_observation",
            retry_count=retry_count,
            observation={
                "cart_total": sum(item.get("price", 0) for item in cart_items),
                "budget_limit": state.get("budget_limit"),
                "valid": ok,
                "reason": reason,
            },
        )

        if ok:
            logs = append_log(logs, node="shopping", event="cart_created")
            return {
                **state,
                "retry_count": retry_count,
                "missing_ingredients": missing,
                "cart_items": cart_items,
                "logs": logs,
                "final_response": "식단 추천, 부족 재료 계산, 쿠팡 장바구니 후보 생성을 완료했습니다.",
            }

        if retry_count >= settings.max_shopping_retries:
            break

        reflection = reflect_failure(reason or "unknown failure", {**state, "reflection": reflection})
        logs = append_log(
            logs,
            node="shopping",
            event="reflexion_generated",
            prompt=REFLEXION_PROMPT,
            reflection=reflection,
        )

    logs = append_log(
        logs,
        node="shopping",
        event="user_approval_required",
        reason=final_reason,
    )
    return {
        **state,
        "retry_count": settings.max_shopping_retries,
        "reflection": reflection,
        "missing_ingredients": missing,
        "cart_items": final_cart_items,
        "logs": logs,
        "final_response": "예산 조건을 만족하지 못해 사용자 승인이 필요합니다.",
    }


def _build_thought(
    missing: list[dict],
    budget_limit: int | None,
    retry_count: int,
    reflection: str | None,
) -> str:
    names = ", ".join(item["name"] for item in missing) or "부족 재료 없음"
    budget = f"{budget_limit}원" if budget_limit is not None else "제한 없음"
    if reflection:
        return (
            f"부족 재료({names})를 예산({budget}) 안에서 담아야 한다. "
            f"이전 회고를 반영한다: {reflection}"
        )
    return f"부족 재료({names})를 계산했고 예산({budget}) 검증까지 진행한다. 시도 {retry_count}."
