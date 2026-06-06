"""Dish Resolver — 셰프형 진입 도구.

v2: 쿼리 길이 기반 HyDE / RAG-Fusion 분기 사용 (smart_search).
없으면 fallback dict 반환 (recipe.py 의 unresolved 템플릿).
"""
from __future__ import annotations

from app.rag.smart_search import smart_search


async def resolve_dish(dish_name: str, *, cuisine_filter: str | None = None, max_time: int | None = None) -> dict:
    """단일 요리명을 받아 recipe_db 상위 1건 반환 (HyDE/RAG-Fusion 자동 분기)."""
    results = await smart_search(
        dish_name,
        k=1,
        cuisine_filter=cuisine_filter,
        max_time=max_time,
    )
    if not results:
        return {
            "id": f"unresolved-{dish_name}",
            "name": dish_name,
            "ingredients": [],
            "steps": [],
            "cuisine_type": cuisine_filter or "기타",
            "resolved": False,
            "source_url": "",
        }

    top = results[0]
    return {
        "id": top.get("id"),
        "name": top.get("name", dish_name),
        "ingredients": top.get("ingredients") or [],
        "steps": top.get("steps") or [],
        "cuisine_type": top.get("cuisine_type", "기타"),
        "time_min": int(top.get("time_min", 30)),
        "calories": int(top.get("calories", 0)),
        "protein": float(top.get("protein", 0)),
        "carb": float(top.get("carb", 0)),
        "fat": float(top.get("fat", 0)),
        "source_url": top.get("source_url", ""),
        "resolved": True,
        "match_distance": top.get("distance"),
    }


async def resolve_dishes(dish_names: list[str], **kwargs) -> list[dict]:
    """다건 요리명 일괄 매칭."""
    return [await resolve_dish(name, **kwargs) for name in dish_names]
