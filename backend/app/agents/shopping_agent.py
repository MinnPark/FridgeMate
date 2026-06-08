import re

from app.config import settings
from app.graph.state import FridgeMateState
from app.llm import generate_json
from app.prompts.shopping_prompts import REACT_PROMPT, REFLEXION_PROMPT
from app.tools.logging_tools import append_log
from app.tools.shopping_tools import (
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


def _normalize_name(name: str) -> str:
    """내부 중복 공백 제거 — "닭  가슴살" → "닭 가슴살" """
    return " ".join(name.split()) if name else ""


def _parse_amount(raw) -> float | None:
    """
    LLM 응답의 amount를 float으로 안전하게 파싱

    처리 케이스:
      12          → 12.0
      12.5        → 12.5
      "12"        → 12.0
      "12g"       → 12.0   (단위가 amount에 섞인 경우)
      "12g+3"     → 12.0   (복합 표현 → 선두 숫자만 추출)
      "6작은술"   → 6.0    (단위가 amount에 섞인 경우)
      "1~2"       → 1.0    (범위 표현 → 최솟값 사용)
      "약간"      → None   (파싱 불가 → None 처리)
      "적당량"    → None
      None        → None
    """
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    if isinstance(raw, str):
        m = re.match(r"(\d+(?:\.\d+)?)", raw.strip())
        if m:
            try:
                return float(m.group(1))
            except ValueError:
                return None
    return None


def _collect_used_recipes(
    meal_plan: dict,
    selected_recipes: list[dict],
) -> tuple[list[dict], list[str]]:
    """
    STEP A: 식단에서 실제 사용된 레시피 + 사용 횟수 추출

    meal_plan.days[].entries[].recipeTitle 기준으로 카운트
    → selected_recipes name 매핑
    → [{"title": str, "count": int, "ingredients": [...]}]

    엣지케이스:
      - recipeTitle이 selected_recipes에 없으면
        ingredients=[] + warnings에 기록 (Coupang 팀이 직접 처리)
      - recipeTitle이 빈 문자열이면 스킵
    """
    # 1. 식단 전체에서 recipeTitle 사용 횟수 집계
    title_counts: dict[str, int] = {}
    for day in meal_plan.get("days", []):
        for entry in day.get("entries", []):
            title = _normalize_name(entry.get("recipeTitle", ""))   # ← 적용
            if title:
                title_counts[title] = title_counts.get(title, 0) + 1

    # 2. selected_recipes name → recipe 역방향 매핑
    recipe_map: dict[str, dict] = {
        _normalize_name(r.get("name", "")): r               # ← 적용
        for r in selected_recipes if r.get("name")
    }

    # 3. 사용 레시피 + 재료 매핑
    warnings: list[str] = []
    used_recipes: list[dict] = []

    for title, count in sorted(title_counts.items()):
        recipe = recipe_map.get(title)
        if recipe is None:
            warnings.append(
                f"'{title}' → selected_recipes에 없음 (ingredients 빈값 처리)"
            )
            used_recipes.append({"title": title, "count": count, "ingredients": []})
        else:
            used_recipes.append({
                "title":       title,
                "count":       count,
                "ingredients": recipe.get("ingredients") or [],
            })

    return used_recipes, warnings


# 허용 단위 목록
_KNOWN_UNITS = {
    "g", "kg", "ml", "l", "개", "장", "줄", "컵",
    "큰술", "작은술", "꼬집", "봉지", "팩", "캔",
}

def _normalize_unit(unit) -> str | None:
    """
    LLM 응답의 unit을 정규화

    처리 케이스:
      "g"       → "g"       (정상)
      "g+3"     → "g"       (앞 알파벳/한글만 추출)
      "ml "     → "ml"      (공백 제거)
      ""        → None
      None      → None
      "g/개"    → "g"       (슬래시 앞 단위만 사용)
    """
    if not unit or not isinstance(unit, str):
        return None
    unit = unit.strip()
    if not unit:
        return None
    # 알려진 단위면 그대로 반환
    if unit in _KNOWN_UNITS:
        return unit
    # 슬래시 구분 → 앞 단위만 사용
    unit = unit.split("/")[0].strip()
    # 앞부분 한글+영문자만 추출 (숫자·특수문자 제거)
    m = re.match(r"([가-힣a-zA-Z]+)", unit)
    return m.group(1) if m else None


def _aggregate_ingredients(used_recipes):
    """
    STEP B: 레시피별 재료를 이름 기준으로 합산
            레시피 사용 횟수(count)만큼 amount 배수 적용

    예) 닭가슴살 두부 강된장 덮밥 (count=2) → 닭가슴살 200g × 2 = 400g

    출력: {
        "양파||g": {"name": "양파", "amount": 300, "unit": "g",
                    "needed_by": ["닭가슴살 두부 강된장 덮밥"]},
        ...
    }

    엣지케이스:
      - 같은 이름, 다른 unit → "이름||unit" 별도 키로 저장 (합산 불가)
      - amount=None          → None 유지 (Coupang 팀이 기본 수량으로 검색)
    """
    aggregated: dict[str, dict] = {}

    for recipe in used_recipes:
        title = recipe["title"]
        count = recipe.get("count", 1)

        for ing in recipe.get("ingredients", []):
            name = _normalize_name(ing.get("name", ""))             # ← 적용
            amount = _parse_amount(ing.get("amount"))
            unit   = _normalize_unit(ing.get("unit"))      # ← _normalize_unit 으로 교체

            if not name:
                continue

            scaled_amount: float | None = (
                amount * count if amount is not None else None
            )

            agg_key = f"{name}||{unit}" if unit else name

            if agg_key not in aggregated:
                aggregated[agg_key] = {
                    "name":      name,
                    "amount":    scaled_amount,
                    "unit":      unit,
                    "needed_by": [title],
                }
            else:
                existing = aggregated[agg_key]
                if title not in existing["needed_by"]:
                    existing["needed_by"].append(title)
                if existing["amount"] is not None and scaled_amount is not None:
                    existing["amount"] += scaled_amount
                elif existing["amount"] is None and scaled_amount is not None:
                    existing["amount"] = scaled_amount

    return aggregated


def _calc_missing(
    aggregated: dict[str, dict],
    pantry_items: list[dict],
) -> list[dict]:
    """
    STEP C: 집계된 재료 중 냉장고(pantry_items)에 없는 재료만 반환

    단순 이름 기준 비교
    (양 비교 미지원 — pantry amount 데이터 신뢰도 낮음)

    출력: [{"name", "amount", "unit", "needed_by"}]  이름 오름차순 정렬
    """
    pantry_names = {
        _normalize_name(item.get("name", ""))               # ← 적용
        for item in pantry_items if item.get("name")
    }

    missing: list[dict] = [
        {
            "name":      item["name"],
            "amount":    item["amount"],
            "unit":      item["unit"],
            "needed_by": item["needed_by"],
        }
        for item in aggregated.values()
        if item["name"] not in pantry_names
    ]

    missing.sort(key=lambda x: x["name"])
    return missing


def _format_quantity(amount: float | None, unit: str | None) -> str | None:
    """
    Coupang 팀 quantity 필드용 수량 문자열 변환

    예)
      200, "g"   → "200g"
      1.5, "kg"  → "1.5kg"
      3,   None  → "3"
      None, "g"  → None
    """
    if amount is None:
        return None
    formatted = int(amount) if float(amount).is_integer() else amount
    return f"{formatted}{unit}" if unit else str(formatted)


def shopping_agent(state: FridgeMateState) -> FridgeMateState:
    """
    입력:
      state["meal_plan"]          (meal_agent 생성)
      state["selected_recipes"]   (recipe_agent 생성, meal_agent에서 오염 없이 유지)
      state["pantry_items"]       (pantry_agent 생성)
      state["mode"]               (today 모드이면 스킵)

    출력:
      state["missing_ingredients"]  → Coupang 팀이 cart_items로 변환
      state["logs"]
    """
    # today 모드 → 장보기 스킵 ← 추가
    mode = state.get("mode", "today")
    if mode == "today":
        return {
            **state,
            "missing_ingredients": [],
            "cart_items":          [],
            "logs": append_log(
                state.get("logs"),
                node="shopping",
                event="skipped",
                result={"reason": "today 모드 — 장보기 계산 불필요"},
            ),
        }

    meal_plan        = state.get("meal_plan") or {}
    selected_recipes = state.get("selected_recipes") or []
    pantry_items     = state.get("pantry_items") or []

    # STEP A: 식단에서 사용 레시피 + 횟수 추출
    used_recipes, step_a_warnings = _collect_used_recipes(meal_plan, selected_recipes)

    # STEP B: 재료 집계 (사용 횟수 × amount)
    aggregated = _aggregate_ingredients(used_recipes)

    # STEP C: 냉장고 비교 → 부족 재료만 추출
    missing = _calc_missing(aggregated, pantry_items)

    logs = append_log(
        state.get("logs"),
        node="shopping",
        event="missing_calculated",
        result={                                          # ← result dict로 묶기
            "used_recipe_count": len(used_recipes),
            "aggregated_count":  len(aggregated),
            "missing_count":     len(missing),
            "missing_names":     [m["name"] for m in missing],
            "warnings":          step_a_warnings,
        },
    )

    return {
        **state,
        "missing_ingredients": missing,
        "logs":                logs,
    }
