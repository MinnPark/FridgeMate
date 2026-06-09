"""예산 Reflexion 도구 — 실가격 확정 후(사용자 선택 이후) 예산 초과 회고.

프론트 CartExecutionCard 가 크롬 확장으로 실제 쿠팡 상품을 검색·선택하면, 그 실가격 합이
예산을 넘을 수 있다. 이 도구는 그 시점에 호출돼:
  ① 각 품목을 더 싼 후보로 교체(swap)
  ② 그래도 초과면 식단 기여가 낮은 품목 제거(drop)
하는 방안을 LLM 자연어 회고와 함께 제안한다. (적용은 프론트에서 사용자 클릭)

LLM = app.llm.generate_json (provider/키/오프라인 폴백 일원화). LLM 실패/오프라인 시
도구 자체의 룰 폴백(최저가 swap → 고가 drop)으로 항상 동작한다.
"""
from __future__ import annotations

import json
from typing import Any

from app.llm import generate_json


BUDGET_REFLEXION_PROMPT = """
당신은 장보기 예산을 맞추는 Shopping Agent의 예산 회고 도구입니다.
사용자가 고른 상품들의 실제 가격 합이 목표 예산을 초과했습니다.
다음 두 가지 행동만으로 예산 이내에 들도록 회고하고 제안하세요.

1) swap: 같은 재료를 더 싼 후보 상품으로 교체 (후보 목록 안에서만)
2) drop: 식단 기여가 낮은(덜 중요한) 재료를 장바구니에서 제거

규칙:
- 먼저 swap 으로 줄이고, 그래도 초과하면 drop 을 추가하세요.
- drop 은 사용 레시피가 적거나 향/양념 등 보조 재료부터. 핵심 단백질·주재료는 최대한 유지.
- swap 의 to_url 은 반드시 해당 재료 candidates 의 url 중 하나여야 합니다.
- 목표: 제안 적용 후 합계 ≤ 예산. 불가능하면 할 수 있는 최선까지만 제안.

JSON object 만 반환:
{
  "reflection": "왜 초과했고 무엇을 바꿨는지 한국어 2~3문장",
  "actions": [
    {"type": "swap", "ingredient": "닭가슴살", "to_url": "https://...", "to_name": "...", "to_price": 5900},
    {"type": "drop", "ingredient": "참기름", "reason": "소량 양념이라 제외"}
  ]
}
""".strip()


def _price(v: Any) -> int:
    try:
        return int(round(float(v)))
    except (TypeError, ValueError):
        return 0


def _selected_price(item: dict) -> int:
    return _price((item.get("selected") or {}).get("price"))


def _rule_fallback(budget: int, items: list[dict]) -> dict:
    """오프라인/LLM 실패용 결정론적 회고: 최저가 swap → 그래도 초과면 고가 drop.

    swap 은 현재 선택가보다 싼 최저가 후보로. drop 은 (swap 반영 후) 가격 높은 순.
    """
    actions: list[dict] = []
    # 품목별 현재가/최저후보 계산
    state: dict[str, dict] = {}
    for it in items:
        ing = it.get("ingredient", "")
        cur = _selected_price(it)
        cands = it.get("candidates") or []
        cheapest = None
        for c in cands:
            cp = _price(c.get("price"))
            if cp <= 0:
                continue
            if cheapest is None or cp < _price(cheapest.get("price")):
                cheapest = c
        state[ing] = {"price": cur, "cheapest": cheapest, "dropped": False}

    # ① swap: 더 싼 후보가 있으면 교체
    for ing, s in state.items():
        ch = s["cheapest"]
        if ch and _price(ch.get("price")) < s["price"]:
            actions.append({
                "type": "swap", "ingredient": ing,
                "to_url": ch.get("url", ""), "to_name": ch.get("name", ""),
                "to_price": _price(ch.get("price")),
            })
            s["price"] = _price(ch.get("price"))

    # ② drop: 여전히 초과면 가격 높은 순으로 제거
    def total() -> int:
        return sum(s["price"] for s in state.values() if not s["dropped"])

    for ing in sorted(state, key=lambda k: state[k]["price"], reverse=True):
        if total() <= budget:
            break
        state[ing]["dropped"] = True
        actions.append({
            "type": "drop", "ingredient": ing,
            "reason": "예산을 맞추기 위해 가격이 높은 품목부터 제외했어요.",
        })

    # 제거될 품목의 교체 제안은 무의미 → 제거(swap 후 drop 중복 방지).
    dropped_ings = {a["ingredient"] for a in actions if a["type"] == "drop"}
    actions = [a for a in actions if not (a["type"] == "swap" and a["ingredient"] in dropped_ings)]

    within = total() <= budget
    reflection = (
        "더 싼 후보로 바꾸고 비싼 품목을 일부 제외해 예산에 맞췄어요."
        if within else
        "더 싼 후보와 일부 제외로 최대한 줄였지만 예산은 여전히 빠듯해요."
    )
    return {"reflection": reflection, "actions": actions, "_projected_total": total()}


def _candidate_urls(item: dict) -> set[str]:
    return {c.get("url", "") for c in (item.get("candidates") or []) if c.get("url")}


def _apply_for_total(budget: int, items: list[dict], actions: list[dict]) -> tuple[int, list[dict]]:
    """actions(검증된)를 반영한 예상 합계 계산. 유효하지 않은 action 은 버림."""
    by_ing = {it.get("ingredient", ""): it for it in items}
    price = {it.get("ingredient", ""): _selected_price(it) for it in items}
    dropped: set[str] = set()
    valid: list[dict] = []
    for a in actions:
        ing = a.get("ingredient", "")
        if ing not in by_ing:
            continue
        if a.get("type") == "swap":
            url = a.get("to_url", "")
            if url not in _candidate_urls(by_ing[ing]):
                continue  # 환각 방지: 실제 후보 url 만
            price[ing] = _price(a.get("to_price"))
            valid.append(a)
        elif a.get("type") == "drop":
            dropped.add(ing)
            valid.append(a)
    projected = sum(p for ing, p in price.items() if ing not in dropped)
    return projected, valid


def build_budget_reflexion(
    *, budget: int, preference: str | None, items: list[dict]
) -> dict:
    current_total = sum(_selected_price(it) for it in items)
    if budget <= 0 or current_total <= budget:
        return {
            "over_budget": False,
            "current_total": current_total,
            "budget": budget,
            "projected_total": current_total,
            "within_after": True,
            "reflection": "예산 이내예요. 조정할 필요가 없어요.",
            "actions": [],
            "used_llm": False,
            "provider": "none",
        }

    fallback = _rule_fallback(budget, items)

    prompt_items = [
        {
            "ingredient": it.get("ingredient", ""),
            "recipe_contexts": it.get("recipe_contexts") or [],
            "selected": {
                "name": (it.get("selected") or {}).get("name"),
                "price": _selected_price(it),
            },
            "candidates": [
                {"name": c.get("name"), "price": _price(c.get("price")),
                 "url": c.get("url"), "delivery": c.get("delivery"),
                 "is_rocket": bool(c.get("isRocket"))}
                for c in (it.get("candidates") or [])
            ],
        }
        for it in items
    ]
    result = generate_json(
        system_prompt=BUDGET_REFLEXION_PROMPT,
        user_prompt=(
            f"목표 예산: {budget}원\n"
            f"현재 합계: {current_total}원 (초과 {current_total - budget}원)\n"
            f"선호 조건: {preference or 'price'}\n"
            f"품목:\n{json.dumps(prompt_items, ensure_ascii=False)}"
        ),
        fallback={"reflection": fallback["reflection"], "actions": fallback["actions"]},
        temperature=0.2,
    )

    raw_actions = result.get("actions")
    if not isinstance(raw_actions, list):
        raw_actions = fallback["actions"]

    projected, valid_actions = _apply_for_total(budget, items, raw_actions)
    # LLM 제안이 예산을 못 맞추면 룰 폴백이 더 나은 경우 그쪽 채택
    if projected > budget:
        fb_proj, fb_valid = _apply_for_total(budget, items, fallback["actions"])
        if fb_proj < projected:
            projected, valid_actions = fb_proj, fb_valid
            result = {"reflection": fallback["reflection"], "_meta": {"used_llm": False, "provider": "fallback"}}

    return {
        "over_budget": True,
        "current_total": current_total,
        "budget": budget,
        "projected_total": projected,
        "within_after": projected <= budget,
        "reflection": str(result.get("reflection") or fallback["reflection"]),
        "actions": valid_actions,
        "used_llm": bool(result.get("_meta", {}).get("used_llm")),
        "provider": result.get("_meta", {}).get("provider", "unknown"),
    }
