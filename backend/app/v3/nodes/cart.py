"""Cart Executor 노드 — 결제 단계 (v3 흐름 마지막의 두 번째).

설계: 4단 폴백 — Coupang Partner API → Naver Shopping → Playwright RPA → 수동 검색링크.
현재(2026-05-28): 최종 폴백(수동 검색링크)만 동작. 상위 3단계 미연결.
관련 미충족: sprint_status #5 외부연동.
"""
from __future__ import annotations

import urllib.parse

from app.v3.state import FridgeMateState


async def cart_node(state: FridgeMateState) -> dict:
    items: list[dict] = []
    for item in state.get("shopping_list", []):
        query = urllib.parse.quote(item["item"])
        items.append({
            "item": item["item"],
            "qty": item["qty"],
            "manual_search_urls": {
                "coupang": f"https://www.coupang.com/np/search?q={query}",
                "naver": f"https://search.shopping.naver.com/search/all?query={query}",
                "kurly": f"https://www.kurly.com/search?sword={query}",
            },
        })

    return {
        "cart_result": {
            "success": True,
            "strategy_used": "manual_links_fallback",
            "cart_url": None,
            "items": items,
            "failed_items": [],
        }
    }
