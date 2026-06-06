"""ChromaDB recipe_db 인덱싱.

오프라인 1회 실행: fetch_cookrcp + fetch_rda → normalize → embed_documents → upsert
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import chromadb

from app.rag.data.fetch_cookrcp import fetch_cookrcp
from app.rag.data.fetch_rda import fetch_rda
from app.rag.embedder import Embedder

COLLECTION_NAME = "recipe_db"
SUB_COLLECTION_NAME = "ingredient_sub"


def get_chroma_client() -> chromadb.PersistentClient:
    path = os.getenv("CHROMADB_PATH", "./data/chroma")
    Path(path).mkdir(parents=True, exist_ok=True)
    return chromadb.PersistentClient(path=path)


def _sanitize_metadata(recipe: dict) -> dict:
    """Chroma 메타데이터는 primitive 만 허용 — list/dict 는 JSON 직렬화."""
    safe: dict[str, str | int | float | bool] = {}
    for k, v in recipe.items():
        if k in ("embed_text",):
            continue
        if isinstance(v, (str, int, float, bool)) or v is None:
            safe[k] = v if v is not None else ""
        else:
            safe[k] = json.dumps(v, ensure_ascii=False)
    return safe


async def upsert_recipes(
    recipes: list[dict],
    *,
    collection_name: str = COLLECTION_NAME,
    batch: int = 64,
) -> dict:
    """증분 주입 — id 기준 upsert. 기존 코퍼스 보존(통째 재구축 X).

    "API로 외부 데이터를 계속 주입" 하는 경로의 정본. 같은 id 재주입 시 갱신, 새 id 추가.
    embed_sig 불일치(다른 임베더로 만든 컬렉션에 섞어넣기) 는 검색을 깨므로 거부한다.
    """
    embedder = Embedder()
    sig = embedder.signature
    client = get_chroma_client()
    col = client.get_or_create_collection(
        collection_name, metadata={"hnsw:space": "cosine", "embed_sig": sig}
    )
    existing_sig = (col.metadata or {}).get("embed_sig")
    if existing_sig and existing_sig != sig:
        raise RuntimeError(
            f"embed_sig 불일치: 컬렉션={existing_sig} ≠ 임베더={sig}. "
            f"같은 EMBED_PROVIDER 로 주입하거나 전체 재구축 후 진행하라."
        )

    from app.rag._normalize import make_embed_text
    for r in recipes:
        if not r.get("embed_text"):
            r["embed_text"] = make_embed_text(r)

    before = col.count()
    for i in range(0, len(recipes), batch):
        chunk = recipes[i:i + batch]
        vecs = await embedder.embed_documents([r["embed_text"] for r in chunk])
        col.upsert(
            ids=[r["id"] for r in chunk],
            documents=[r["embed_text"] for r in chunk],
            embeddings=vecs,
            metadatas=[_sanitize_metadata(r) for r in chunk],
        )
    after = col.count()
    return {
        "collection": collection_name,
        "embed_sig": sig,
        "before": before,
        "after": after,
        "added": after - before,
        "submitted": len(recipes),
    }


async def build_recipe_db(limit: int = 200) -> dict:
    print(f"[indexer] 데이터 수집 중... (limit={limit})")
    cookrcp = await fetch_cookrcp(limit=limit)
    rda = await fetch_rda(limit=limit)

    # 중복 제거 (id 기준)
    seen: dict[str, dict] = {}
    for r in cookrcp + rda:
        if r["id"] not in seen:
            seen[r["id"]] = r
    recipes = list(seen.values())
    print(f"[indexer] 정규화 완료: {len(recipes)} 건")

    embedder = Embedder()
    texts = [r["embed_text"] for r in recipes]
    print(f"[indexer] 임베딩 중... (mock={embedder.mock})")
    embeddings = await embedder.embed_documents(texts)

    client = get_chroma_client()
    # 기존 컬렉션이 다른 차원이면 삭제 후 재생성
    try:
        existing = client.get_collection(COLLECTION_NAME)
        client.delete_collection(COLLECTION_NAME)
    except Exception:
        pass
    col = client.create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine", "embed_sig": embedder.signature},
    )

    col.add(
        ids=[r["id"] for r in recipes],
        documents=texts,
        embeddings=embeddings,
        metadatas=[_sanitize_metadata(r) for r in recipes],
    )

    print(f"[indexer] 인덱싱 완료: {col.count()} 건 → {COLLECTION_NAME}")
    return {"collection": COLLECTION_NAME, "count": col.count(), "embed_sig": embedder.signature}


if __name__ == "__main__":
    asyncio.run(build_recipe_db())
