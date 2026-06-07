from typing import Any
from urllib.parse import quote


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
