from typing import Any
from urllib.parse import quote
from langchain_core.tools import tool


def search_coupang_products(
    missing_ingredients: list[dict[str, Any]],
    reflection: str | None = None,
) -> list[dict[str, Any]]:
    prefer_budget = bool(reflection)
    products = []
    for ingredient in missing_ingredients:
        base_price = 1800 if prefer_budget else 2500
        products.append(
            {
                "ingredient": ingredient["name"],
                "product_name": (
                    f"FridgeMate 예산형 {ingredient['name']}"
                    if prefer_budget
                    else f"FridgeMate 추천 {ingredient['name']}"
                ),
                "quantity": f"{ingredient['amount']}{ingredient['unit']}",
                "price": base_price,
                "search_strategy": "budget_first" if prefer_budget else "quality_first",
            }
        )
    return products


def create_cart_deeplinks(products: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cart_items = []
    for product in products:
        query = quote(product["product_name"])
        cart_items.append(
            {
                **product,
                "deeplink": f"https://www.coupang.com/np/search?q={query}",
            }
        )
    return cart_items


def validate_budget(
    cart_items: list[dict[str, Any]],
    budget_limit: int | None,
) -> tuple[bool, str | None]:
    if budget_limit is None:
        return True, None
    total = sum(item.get("price", 0) for item in cart_items)
    if total <= budget_limit:
        return True, None
    return False, f"budget exceeded: total={total}, budget={budget_limit}"


# ── /chat/tool 전용 Tool Calling wrapper ───────────────────────────────────
@tool
def search_coupang_products_tool(
    missing_ingredients: list,
    reflection: str | None = None,
) -> list:
    """
    냉장고에 없는 부족 재료 목록을 기반으로
    쿠팡 상품을 검색하고 장보기 목록을 생성합니다.

    아래 두 조건을 모두 만족할 때만 호출하세요:
    ① mode가 today가 아닐 때 (weekend/mealprep/goal)
    ② 부족한 재료가 실제로 존재할 때

    호출 금지 조건:
    - today 모드 (지금 당장 냉장고 재료만 사용)
    - 부족한 재료가 없을 때 (냉장고에 모두 있을 때)

    Args:
        missing_ingredients: 부족한 재료 목록
                             [{"name": str, "amount": float, "unit": str}]
        reflection:          예산 초과 시 재시도 여부 (기본 None)

    Returns:
        [
            {
                "ingredient":      "된장",
                "product_name":    "FridgeMate 추천 된장",
                "quantity":        "60g",
                "price":           2500,
                "search_strategy": "quality_first",
            },
            ...
        ]
    """
    return search_coupang_products(missing_ingredients, reflection)  # 기존 함수 그대로 호출
