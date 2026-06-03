import re
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
