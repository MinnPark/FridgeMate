"""user_preference 컬렉션 — 장기 개인화 메모리 (기획안 정본).

히스토리 누적 → 선호 벡터 → 검색 boost 파이프라인의 가운데 단계.
- record_preference: 수락한 레시피를 user_id 별 선호 벡터로 적재.
- get_preference_centroid: 사용자 선호 벡터들의 평균(취향 중심).
- boost_by_preference: 검색 결과를 선호 centroid 유사도로 re-rank (§5b 개인화).

영구 원천 이력은 backend/persistence/history_store.py (Postgres/SQLite).
이 컬렉션은 그 이력에서 파생된 '검색용' 벡터 — 재생성 가능.
docs/data_architecture.md §4 참조.
"""
from __future__ import annotations

import math
import time
from typing import Optional

from app.rag.embedder import CohereEmbedder
from app.rag.indexer import COLLECTION_NAME, get_chroma_client

PREF_COLLECTION = "user_preference"


def _pref_col():
    client = get_chroma_client()
    return client.get_or_create_collection(PREF_COLLECTION, metadata={"hnsw:space": "cosine"})


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (na * nb)


async def record_preference(
    user_id: str,
    recipe_id: str,
    embed_text: str,
    *,
    accepted: bool = True,
    meta: Optional[dict] = None,
) -> None:
    """사용자가 수락/선호한 레시피 1건을 선호 벡터로 upsert."""
    emb = CohereEmbedder()
    vec = (await emb.embed_documents([embed_text]))[0]
    md: dict = {"user_id": user_id, "recipe_id": recipe_id, "accepted": accepted, "ts": time.time()}
    if meta:
        md.update({k: v for k, v in meta.items() if isinstance(v, (str, int, float, bool))})
    _pref_col().upsert(
        ids=[f"{user_id}::{recipe_id}"],
        documents=[embed_text],
        embeddings=[vec],
        metadatas=[md],
    )


async def get_preference_centroid(user_id: str) -> Optional[list[float]]:
    """user_id 의 선호 벡터 평균(centroid). 이력 없으면 None."""
    got = _pref_col().get(where={"user_id": user_id}, include=["embeddings"])
    raw = got.get("embeddings")
    embs = list(raw) if raw is not None else []
    if len(embs) == 0:
        return None
    dim = len(embs[0])
    return [sum(e[i] for e in embs) / len(embs) for i in range(dim)]


async def boost_by_preference(
    user_id: str,
    docs: list[dict],
    *,
    k: int = 3,
    weight: float = 0.3,
) -> list[dict]:
    """검색 결과를 선호 centroid 유사도로 re-rank.

    final = (1-weight)·base + weight·pref_sim
      base     = 1 - distance (검색 근접도; distance 없으면 0.5)
      pref_sim = cos(doc_vec, user_centroid)
    선호 이력 없으면 원본 순서 유지(상위 k).
    """
    if not docs:
        return docs
    centroid = await get_preference_centroid(user_id)
    if not centroid:
        return docs[:k]

    # doc 벡터는 recipe_db 에서 id 로 회수 (재임베딩 회피)
    client = get_chroma_client()
    rcol = client.get_or_create_collection(COLLECTION_NAME, metadata={"hnsw:space": "cosine"})
    ids = [d.get("id") for d in docs if d.get("id")]
    id2vec: dict[str, list[float]] = {}
    if ids:
        got = rcol.get(ids=ids, include=["embeddings"])
        got_ids = got.get("ids") or []
        got_embs = got.get("embeddings")
        got_embs = list(got_embs) if got_embs is not None else []
        id2vec = dict(zip(got_ids, got_embs))

    for d in docs:
        vec = id2vec.get(d.get("id"))
        dist = d.get("distance")
        base = (1.0 - dist) if isinstance(dist, (int, float)) else 0.5
        pref = _cosine(vec, centroid) if vec is not None else 0.0
        d["_pref_sim"] = round(pref, 4)
        d["_final"] = round((1 - weight) * base + weight * pref, 4)

    return sorted(docs, key=lambda x: x.get("_final", 0.0), reverse=True)[:k]


def reset_user(user_id: str) -> int:
    """user_id 선호 전부 삭제. 반환: 삭제 건수."""
    col = _pref_col()
    got = col.get(where={"user_id": user_id})
    ids = got.get("ids") or []
    if ids:
        col.delete(ids=ids)
    return len(ids)
