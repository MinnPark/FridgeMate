"""ChromaDB retriever — embed_query 로 검색.

Sprint 1: 기본 Top-k + 메타데이터 pre-filter.
Sprint 2: HyDE (짧은 쿼리) / RAG-Fusion (복합 조건) 분기.
"""
from __future__ import annotations

import json
from typing import Optional

from app.rag.embedder import Embedder
from app.rag.indexer import COLLECTION_NAME, get_chroma_client


def _decode_meta(meta: dict) -> dict:
    """indexer 에서 JSON 직렬화된 list/dict 를 복원."""
    out = dict(meta)
    for key in ("ingredients", "steps"):
        if isinstance(out.get(key), str):
            try:
                out[key] = json.loads(out[key])
            except Exception:
                pass
    return out


async def search_recipes(
    query: str,
    *,
    k: int = 3,
    cuisine_filter: Optional[str] = None,
    max_time: Optional[int] = None,
) -> list[dict]:
    embedder = Embedder()
    query_vec = await embedder.embed_query(query)

    # ChromaDB는 다중 조건 시 $and 래핑 필수
    conds: list[dict] = []
    if cuisine_filter:
        conds.append({"cuisine_type": cuisine_filter})
    if max_time:
        conds.append({"time_min": {"$lte": max_time}})
    if len(conds) > 1:
        where = {"$and": conds}
    elif conds:
        where = conds[0]
    else:
        where = None

    client = get_chroma_client()
    col = client.get_or_create_collection(COLLECTION_NAME, metadata={"hnsw:space": "cosine"})

    results = col.query(
        query_embeddings=[query_vec],
        n_results=k,
        where=where,
    )

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
        docs.append(item)
    return docs
