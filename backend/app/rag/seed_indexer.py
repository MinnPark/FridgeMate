"""시드 레시피 자동 인덱싱 — 앱 시작 시 호출.

ChromaDB recipe_db 컬렉션이 비어있으면 seed_recipes.json 을 인덱싱한다.
이미 인덱싱돼 있으면 skip (idempotent).

Cohere 활성 시: 실제 임베딩. 비활성 시: mock bag-of-tokens.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from app.rag._normalize import make_embed_text
from app.rag.embedder import CohereEmbedder
from app.rag.indexer import COLLECTION_NAME, _sanitize_metadata, get_chroma_client

SEED_PATH = Path(__file__).resolve().parents[1] / "data" / "seed_recipes.json"


async def ensure_seed_indexed(force: bool = False) -> dict:
    # 임베더 시그니처 가드 — 인덱스/쿼리 임베딩 공간 불일치(예: mock↔bge-m3) 자동 감지·재인덱싱.
    # 같은 컬렉션을 다른 임베더로 쿼리하면 검색이 깨지므로(공간 불일치) 시그니처 바뀌면 재구축.
    embedder = CohereEmbedder()
    sig = embedder.signature
    client = get_chroma_client()
    col = client.get_or_create_collection(
        COLLECTION_NAME, metadata={"hnsw:space": "cosine", "embed_sig": sig}
    )
    existing_sig = (col.metadata or {}).get("embed_sig")

    if not force and col.count() > 0 and existing_sig == sig:
        return {"collection": COLLECTION_NAME, "count": col.count(), "skipped": True, "embed_sig": sig}

    reason = "force" if force else ("empty" if col.count() == 0 else f"embed_sig {existing_sig}→{sig}")
    try:
        client.delete_collection(COLLECTION_NAME)
    except Exception:
        pass
    col = client.create_collection(COLLECTION_NAME, metadata={"hnsw:space": "cosine", "embed_sig": sig})

    recipes = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    for r in recipes:
        r["embed_text"] = make_embed_text(r)

    texts = [r["embed_text"] for r in recipes]
    embeddings = await embedder.embed_documents(texts)

    col.add(
        ids=[r["id"] for r in recipes],
        documents=texts,
        embeddings=embeddings,
        metadatas=[_sanitize_metadata(r) for r in recipes],
    )
    return {
        "collection": COLLECTION_NAME,
        "count": col.count(),
        "skipped": False,
        "embedder_mock": embedder.mock,
        "embed_sig": sig,
        "rebuilt": reason,
    }


if __name__ == "__main__":
    res = asyncio.run(ensure_seed_indexed(force=True))
    print(res)
