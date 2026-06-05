"""RAG-Fusion — 복합 조건 쿼리(≥ 10자) 에 적합.

LLM 이 4개 다각도 쿼리 생성 → 각각 검색 → RRF(Reciprocal Rank Fusion) 로 재순위.
LLM 비활성 시: 일반 retriever 로 fallback.
"""
from __future__ import annotations

import asyncio
from typing import Optional

from app.rag.retriever import search_recipes
from app.rag._llm import call_llm, llm_enabled

MULTI_QUERY_SYSTEM_PROMPT_NAME = "rag_fusion_multi_query"
RRF_K_CONST = 60


def reciprocal_rank_fusion(result_lists: list[list[dict]], k_top: int = 5) -> list[dict]:
    """RRF: score(d) = Σ 1 / (rank + RRF_K_CONST)."""
    scores: dict[str, float] = {}
    items: dict[str, dict] = {}
    for results in result_lists:
        for rank, doc in enumerate(results):
            doc_id = doc.get("id") or doc.get("name", "?")
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (rank + RRF_K_CONST)
            items.setdefault(doc_id, doc)
    ranked_ids = sorted(scores, key=lambda i: scores[i], reverse=True)[:k_top]
    return [{**items[i], "_rrf_score": round(scores[i], 5)} for i in ranked_ids]


async def rag_fusion_search(
    query: str,
    *,
    k: int = 3,
    cuisine_filter: Optional[str] = None,
    max_time: Optional[int] = None,
) -> list[dict]:
    if not llm_enabled():
        return await search_recipes(query, k=k, cuisine_filter=cuisine_filter, max_time=max_time)

    raw = await call_llm(
        system_prompt_name=MULTI_QUERY_SYSTEM_PROMPT_NAME,
        user_content=query,
        fallback="",
        max_tokens=200,
    )
    queries = [q.strip() for q in raw.splitlines() if q.strip()][:4]
    if not queries:
        return await search_recipes(query, k=k, cuisine_filter=cuisine_filter, max_time=max_time)

    results = await asyncio.gather(*[
        search_recipes(q, k=k, cuisine_filter=cuisine_filter, max_time=max_time)
        for q in queries
    ])
    fused = reciprocal_rank_fusion(results, k_top=k)
    for d in fused:
        d["_via"] = "rag_fusion"
    return fused
