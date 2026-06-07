"""RAG-Fusion — 복합 조건 쿼리(≥ 10자) 에 적합.

LLM 이 4개 다각도 쿼리 생성 → 각각 검색 → RRF(Reciprocal Rank Fusion) 로 재순위.
LLM 비활성 시: 일반 retriever 로 fallback.
"""
from __future__ import annotations

import asyncio
import re
from typing import Optional

from app.rag.retriever import search_recipes
from app.rag._llm import call_llm, llm_enabled, rag_subquery_provider

MULTI_QUERY_SYSTEM_PROMPT_NAME = "rag_fusion_multi_query"
RRF_K_CONST = 60
_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")
_KOREAN_RE = re.compile(r"[가-힣]")
_LATIN_RE = re.compile(r"[A-Za-z]")
_LIST_PREFIX_RE = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s*")
_META_TERMS = ("규칙", "검색 쿼리", "생성任务", "사용자", "출력", "줄바꿈")


def _sanitize_queries(raw: str, original_query: str, limit: int = 4) -> list[str]:
    """로컬 LLM의 다국어 지시문 반복을 제거하고 검색 가능한 한국어 쿼리만 남긴다."""
    queries: list[str] = []
    for line in raw.splitlines():
        candidate = _LIST_PREFIX_RE.sub("", line).strip().strip("\"'`")
        compact_length = len(candidate.replace(" ", ""))
        if (
            not candidate
            or _CJK_RE.search(candidate)
            or _LATIN_RE.search(candidate)
            or not _KOREAN_RE.search(candidate)
            or not 2 <= compact_length <= 30
            or any(term in candidate for term in _META_TERMS)
        ):
            continue
        if candidate not in queries:
            queries.append(candidate)
        if len(queries) == limit:
            return queries

    fallback_queries = [
        original_query.strip(),
        f"{original_query.strip()} 레시피",
        f"{original_query.strip()} 추천",
        f"{original_query.strip()} 요리",
    ]
    for candidate in fallback_queries:
        if candidate and candidate not in queries:
            queries.append(candidate)
        if len(queries) == limit:
            break
    return queries


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
    provider = rag_subquery_provider()
    if not llm_enabled(provider):
        return await search_recipes(query, k=k, cuisine_filter=cuisine_filter, max_time=max_time)

    raw = await call_llm(
        system_prompt_name=MULTI_QUERY_SYSTEM_PROMPT_NAME,
        user_content=query,
        provider=provider,
        fallback="",
        max_tokens=200,
    )
    queries = _sanitize_queries(raw, query)
    if not queries:
        return await search_recipes(query, k=k, cuisine_filter=cuisine_filter, max_time=max_time)

    # RRF 융합 이득은 후보 풀이 클수록 커진다. 서브쿼리는 넓게(k_fetch) 뽑고  (튜닝 사유: docs/rag-tuning-changelog.md 변경1)
    # 융합 후 k_top=k 로 자른다. (fetch==final 이면 4쿼리×k 에서 k 뽑기라 융합이 형식만 남음)
    k_fetch = max(k * 3, 20)
    gathered = await asyncio.gather(*[
        search_recipes(q, k=k_fetch, cuisine_filter=cuisine_filter, max_time=max_time)
        for q in queries
    ], return_exceptions=True)
    results: list[list[dict]] = []
    for subquery, result in zip(queries, gathered):
        if isinstance(result, BaseException):
            print(
                f"[RAG/Fusion] subquery failed: q={subquery!r} "
                f"error={type(result).__name__}: {result}",
                flush=True,
            )
            continue
        results.append(result)

    if not results:
        print(
            "[RAG/Fusion] all subqueries failed; returning no results "
            "so the agent workflow can continue",
            flush=True,
        )
        return []

    fused = reciprocal_rank_fusion(results, k_top=k)
    for d in fused:
        d["_via"] = "rag_fusion"
    # 메커니즘 가시화: 다각도 멀티쿼리 + RRF 융합결과(출처)
    print(f"[RAG/Fusion] q={query!r}", flush=True)
    print(f"[RAG/Fusion] multi_queries(LLM:{provider}): {queries}", flush=True)
    for d in fused:
        print(f"[RAG/Fusion]   -> {d.get('name')} | rrf={d.get('_rrf_score')} | src={d.get('source')} | cite={d.get('source_url','')}", flush=True)
    return fused
