"""HyDE — Hypothetical Document Embeddings.

짧고 모호한 쿼리(< 10자) 에 적합.
LLM 으로 가상 레시피 1단락 생성 → 그걸 임베딩 → ChromaDB 검색.
LLM 비활성 시: 일반 retriever 로 fallback.
"""
from __future__ import annotations

from typing import Optional

from app.rag.embedder import Embedder
from app.rag.indexer import COLLECTION_NAME, get_chroma_client
from app.rag.retriever import _decode_meta, search_recipes
from app.rag._llm import call_llm, llm_enabled

HYDE_SYSTEM_PROMPT_NAME = "hyde_recipe"


async def hyde_search(
    query: str,
    *,
    k: int = 3,
    cuisine_filter: Optional[str] = None,
    max_time: Optional[int] = None,
) -> list[dict]:
    if not llm_enabled():
        return await search_recipes(query, k=k, cuisine_filter=cuisine_filter, max_time=max_time)

    hypo_doc = await call_llm(
        system_prompt_name=HYDE_SYSTEM_PROMPT_NAME,
        user_content=query,
        fallback="",
        max_tokens=200,
    )
    if not hypo_doc:
        return await search_recipes(query, k=k, cuisine_filter=cuisine_filter, max_time=max_time)

    embedder = Embedder()
    hypo_vec = (await embedder.embed_documents([hypo_doc]))[0]

    conds: list[dict] = []
    if cuisine_filter:
        conds.append({"cuisine_type": cuisine_filter})
    if max_time:
        conds.append({"time_min": {"$lte": max_time}})
    where = {"$and": conds} if len(conds) > 1 else (conds[0] if conds else None)

    client = get_chroma_client()
    col = client.get_or_create_collection(COLLECTION_NAME, metadata={"hnsw:space": "cosine"})
    results = col.query(query_embeddings=[hypo_vec], n_results=k, where=where)

    docs = []
    metas = results.get("metadatas") or [[]]
    ids = results.get("ids") or [[]]
    distances = results.get("distances") or [[]]
    if not metas or not metas[0]:
        return docs
    for i, meta in enumerate(metas[0]):
        item = _decode_meta(meta)
        item["id"] = ids[0][i] if i < len(ids[0]) else item.get("id")
        item["distance"] = distances[0][i] if i < len(distances[0]) else None
        item["_via"] = "hyde"
        docs.append(item)
    return docs
