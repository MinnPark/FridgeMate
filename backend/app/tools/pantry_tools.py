import re
from datetime import date, datetime
from typing import Any


KNOWN_INGREDIENTS = ["두부", "계란", "애호박", "시금치", "밥", "된장", "닭가슴살"]


def parse_pantry_items(user_input: str) -> list[dict[str, Any]]:
    """Function Calling target: normalize free-form pantry text into JSON."""
    items = []
    for ingredient in KNOWN_INGREDIENTS:
        if ingredient in user_input:
            items.append(
                {
                    "name": ingredient,
                    "amount": _extract_amount(user_input, ingredient),
                    "unit": "개" if ingredient in ["계란", "애호박"] else "g",
                    "expiry_priority": "high" if ingredient in ["두부", "애호박"] else "normal",
                }
            )
    return items


def _extract_amount(user_input: str, ingredient: str) -> int:
    pattern = rf"(\d+)\s*(개|g|그램)?\s*{ingredient}"
    match = re.search(pattern, user_input)
    if not match:
        return 1 if ingredient in ["계란", "애호박"] else 100
    return int(match.group(1))


def parse_amount_unit(amount_str: str | None) -> tuple[float | None, str | None]:
    if not amount_str:
        return None, None
    match = re.match(r"([\d.]+)\s*([^\d\s]+)", amount_str.strip())
    if match:
        return float(match.group(1)), match.group(2)
    return None, amount_str


def calculate_days_left(expiration_date: str | None) -> int | None:
    if not expiration_date:
        return None
    try:
        exp_date = datetime.strptime(expiration_date, "%Y-%m-%d").date()
        return (exp_date - date.today()).days
    except ValueError:
        return None


def expiry_priority_from_days(days: int | None) -> str:
    if days is None:
        return "normal"
    return "high" if days <= 3 else "normal"


def freshness_from_days(days: int | None) -> str:
    if days is None:
        return "fresh"
    if days <= 3:
        return "urgent"
    if days <= 7:
        return "soon"
    return "fresh"


def build_pantry_items(entries: list[dict]) -> list[dict]:
    items = []
    for entry in entries:
        amount_val, unit = parse_amount_unit(entry.get("amount"))
        days_left = calculate_days_left(entry.get("expiration_date"))

        items.append({
            "name": entry.get("name", ""),
            "amount": amount_val,
            "unit": unit,
            "expiry_priority": expiry_priority_from_days(days_left),
            "expiration_date": entry.get("expiration_date"),
            "storage_type": entry.get("storage_type"),
        })
    return items


def build_pantry_analysis(pantry_items: list[dict]) -> dict:
    ui_items = []
    for item in pantry_items:
        days_left = calculate_days_left(item.get("expiration_date"))
        freshness = freshness_from_days(days_left)

        if days_left is None:
            expiry_label = None
        elif days_left <= 0:
            expiry_label = "만료됨"
        else:
            expiry_label = f"{days_left}일 남음"

        amount_str = (
            f"{int(item['amount'])}{item['unit']}"
            if item.get("amount") and item.get("unit")
            else None
        )

        ui_items.append({
            "name": item["name"],
            "category": "재료",
            "freshness": freshness,
            "amount": amount_str,
            "expiry_label": expiry_label,
            "note": item.get("storage_type"),
        })

    priority_use = [
        item["name"]
        for item in pantry_items
        if item.get("expiry_priority") == "high"
    ]

    if priority_use:
        names_str = ", ".join(priority_use)
        summary = f"유통기한이 가까운 {names_str}을(를) 우선 사용하는 식단을 구성할게요."
    else:
        summary = "냉장고 재료를 균형 있게 활용하는 식단을 구성할게요."

    return {
        "items": ui_items,
        "priority_use": priority_use,
        "summary": summary,
    }
