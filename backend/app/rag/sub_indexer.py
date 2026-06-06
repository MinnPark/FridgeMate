"""ingredient_sub 컬렉션 인덱싱 — 대체재 지식 베이스 (기획안 정본).

원재료명 → 대체재 후보. substitute_finder(shopping_rank 예산 Reflexion)가 검색.
원재료+대체재+사유 텍스트를 벡터화 → 부족재료명으로 유사검색.
seed_indexer 와 동일 패턴 (idempotent, mock/local/cohere 임베딩 자동).
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Optional

from app.rag.embedder import Embedder
from app.rag.indexer import SUB_COLLECTION_NAME, _sanitize_metadata, get_chroma_client

SEED_PATH = Path(__file__).resolve().parents[1] / "data" / "ingredient_sub_seed.json"


def _embed_text(entry: dict) -> str:
    subs = ", ".join(entry.get("substitutes") or [])
    reasons = ", ".join(entry.get("reason_types") or [])
    return f"{entry['original']} 대체재: {subs} 사유: {reasons} {entry.get('note','')}"


async def ensure_sub_indexed(force: bool = False) -> dict:
    emb = Embedder()
    sig = emb.signature
    client = get_chroma_client()
    col = client.get_or_create_collection(
        SUB_COLLECTION_NAME, metadata={"hnsw:space": "cosine", "embed_sig": sig}
    )
    existing_sig = (col.metadata or {}).get("embed_sig")

    if not force and col.count() > 0 and existing_sig == sig:
        return {"collection": SUB_COLLECTION_NAME, "count": col.count(), "skipped": True, "embed_sig": sig}
    try:
        client.delete_collection(SUB_COLLECTION_NAME)
    except Exception:
        pass
    col = client.create_collection(SUB_COLLECTION_NAME, metadata={"hnsw:space": "cosine", "embed_sig": sig})

    entries = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    texts = [_embed_text(e) for e in entries]
    vecs = await emb.embed_documents(texts)
    col.add(
        ids=[e["id"] for e in entries],
        documents=texts,
        embeddings=vecs,
        metadatas=[_sanitize_metadata(e) for e in entries],
    )
    return {"collection": SUB_COLLECTION_NAME, "count": col.count(), "skipped": False,
            "embedder_mock": emb.mock}


async def find_substitutes(ingredient: str, *, k: int = 3) -> list[dict]:
    """부족 재료명 → 대체재 후보 (유사검색). substitute_finder 진입점."""
    emb = Embedder()
    qv = await emb.embed_query(ingredient)
    client = get_chroma_client()
    col = client.get_or_create_collection(SUB_COLLECTION_NAME, metadata={"hnsw:space": "cosine"})
    res = col.query(query_embeddings=[qv], n_results=k)
    metas = res.get("metadatas") or [[]]
    dists = res.get("distances") or [[]]
    out = []
    for i, m in enumerate(metas[0] if metas else []):
        item = dict(m)
        for key in ("substitutes", "reason_types"):
            if isinstance(item.get(key), str):
                try:
                    item[key] = json.loads(item[key])
                except Exception:
                    pass
        item["distance"] = dists[0][i] if i < len(dists[0]) else None
        out.append(item)
    return out


if __name__ == "__main__":
    print(asyncio.run(ensure_sub_indexed(force=True)))
