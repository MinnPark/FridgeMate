"""쿼리 길이 기반 HyDE / RAG-Fusion 분기 (셰프형 v2 핵심 RAG 진입점).

CLAUDE.md 5b 규칙:
  len(query) < 10  → hyde_search
  else             → rag_fusion_search
모든 검색은 user_preference 벡터 boost (Sprint 3) 예정.
"""
from __future__ import annotations

from typing import Optional

from app.rag.hyde import hyde_search
from app.rag.rag_fusion import rag_fusion_search
from app.rag.retriever import search_recipes

HYDE_THRESHOLD = 10


async def smart_search(
    query: str,
    *,
    k: int = 3,
    cuisine_filter: Optional[str] = None,
    max_time: Optional[int] = None,
) -> list[dict]:
    """쿼리 길이로 HyDE/RAG-Fusion 분기. 빈 쿼리는 일반 검색."""
    q = (query or "").strip()
    if not q:
        return await search_recipes(q, k=k, cuisine_filter=cuisine_filter, max_time=max_time)
    if len(q.replace(" ", "")) < HYDE_THRESHOLD:
        return await hyde_search(q, k=k, cuisine_filter=cuisine_filter, max_time=max_time)
    return await rag_fusion_search(q, k=k, cuisine_filter=cuisine_filter, max_time=max_time)
