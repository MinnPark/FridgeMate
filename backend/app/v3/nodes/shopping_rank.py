"""Shopping Rank 노드 — v3. 부족 재료별 상품 후보군 순위 매김.

입력: state["missing_ingredients"] (gap_calc 출력)
출력:
  - shopping_candidates: 부족 재료 1건당 상품 후보 N개 (rank 1..N, selected 플래그)
  - shopping_list: selected=True 인 후보만 추린 결제 대상 (cart 입력)

순위: unit_price 낮음 + 배송 빠름 + (reflexion 시) 대체재 우선.
사용자 장바구니 선택점: rank 1 기본 selected=True. UI 가 selected 토글 후 /api/run 재호출.
reflexion: missing item decision=="substitute" 면 대체재 후보를 선택 (20% 저렴 가정).

Sprint(후속): Naver Shopping / Coupang product_search 실제 연결 + substitute_finder 영양영향 계산.
"""
from __future__ import annotations

import urllib.parse

from app.v3.state import FridgeMateState
from app.v3.tools.budget_validator import validate_budget

# mock 단가표 (1패키지 기준) — 실제 product_search 가 대체
MOCK_PACKAGE_PRICE = {
    "김치": 6000, "돼지고기": 8000, "두부": 2500, "대파": 1500, "쌀": 22000,
    "시금치": 3000, "당근": 2000, "고추장": 5000, "참기름": 4500, "계란": 4000,
    "마늘": 3000, "양파": 2500, "스파게티 면": 3500, "올리브유": 12000,
    "베이컨": 5500, "토마토소스": 4500, "주재료": 7000,
}
DEFAULT_PRICE = 4000
CANDIDATES_PER_ITEM = 3


def _search_url(name: str) -> str:
    return f"https://search.shopping.naver.com/search/all?query={urllib.parse.quote(name)}"


def _packages(qty: float, unit: str) -> int:
    if unit in ("g", "ml"):
        return 1
    return max(1, int(qty))


def _candidates_for(item: dict) -> list[dict]:
    """부족 재료 1건 → 상품 후보 N개 (순위). reflexion 대체 요청 반영."""
    name = item["name"]
    qty = item.get("shortage_qty", 1)
    unit = item.get("unit") or ""
    packages = _packages(qty, unit)
    base = MOCK_PACKAGE_PRICE.get(name, DEFAULT_PRICE)
    want_substitute = item.get("decision") == "substitute"

    raw = [
        {"product_name": f"{name} (로켓배송)", "unit_price": base * 1.1, "delivery": "로켓배송", "substituted": False},
        {"product_name": f"{name} (일반)",     "unit_price": base * 1.0, "delivery": "일반배송", "substituted": False},
        {"product_name": f"{name} 대체상품",   "unit_price": base * 0.8, "delivery": "일반배송", "substituted": True},
    ]
    # 정렬: 대체 요청 시 대체재 우선, 그 외엔 단가 낮은 순 + 빠른 배송 가산
    def sort_key(c: dict) -> tuple:
        sub_pref = 0 if (want_substitute and c["substituted"]) else 1
        delivery_bonus = 0 if c["delivery"] == "로켓배송" else 1
        return (sub_pref, round(c["unit_price"]), delivery_bonus)

    raw.sort(key=sort_key)

    out: list[dict] = []
    for rank, c in enumerate(raw[:CANDIDATES_PER_ITEM], start=1):
        out.append({
            "ingredient": name,
            "rank": rank,
            "product_name": c["product_name"],
            "unit_price": round(c["unit_price"]),
            "price": int(round(c["unit_price"])) * packages,
            "delivery": c["delivery"],
            "product_url": _search_url(name),
            "substituted": c["substituted"],
            "selected": rank == 1,   # 기본: 최상위 후보 선택
            "qty": qty,
            "unit": unit,
            "packages": packages,
            "used_in": item.get("used_in", []),
        })
    return out


async def shopping_rank_node(state: FridgeMateState) -> dict:
    missing = state.get("missing_ingredients") or []

    # UI 가 사용자 선택을 넘겼으면(shopping_candidates 에 selected 토글) 그대로 존중,
    # 아니면 새로 후보군 생성.
    incoming = state.get("shopping_candidates") or []
    if incoming and not _stale(incoming, missing):
        candidates = incoming
    else:
        candidates = []
        for item in missing:
            if item.get("decision") == "skip":
                continue
            candidates.extend(_candidates_for(item))

    selected = [c for c in candidates if c.get("selected")]
    substitutes_used = sum(1 for c in selected if c.get("substituted"))

    shopping_list = [{
        "item": c["ingredient"],
        "qty": c.get("qty", 1),
        "unit": c.get("unit", ""),
        "packages": c.get("packages", 1),
        "price": c["price"],
        "product_name": c["product_name"],
        "product_url": c["product_url"],
        "substituted": c["substituted"],
        "used_in": c.get("used_in", []),
    } for c in selected]

    total = sum(s["price"] for s in shopping_list)
    budget_check = validate_budget(total, state.get("budget", 0))

    return {
        "shopping_candidates": candidates,
        "shopping_list": shopping_list,
        "kpi_log": {
            **(state.get("kpi_log") or {}),
            "budget_compliance": budget_check["ok"],
            "budget_over_pct": budget_check["over_pct"],
            "substitutes_used": substitutes_used,
        },
    }


def _stale(candidates: list[dict], missing: list[dict]) -> bool:
    """후보군이 현재 부족 재료 집합과 안 맞으면(재구성 후) stale."""
    cand_ings = {c.get("ingredient") for c in candidates}
    miss_ings = {m["name"] for m in missing if m.get("decision") != "skip"}
    return cand_ings != miss_ings
