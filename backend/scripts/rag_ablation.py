"""embed_text ablation — V1(현행) vs V2(lean) plain 정확도 비교.

프로덕션 recipe_db(1693, V1)는 그대로 두고, 같은 레시피를 V2 lean embed_text 로
임시 컬렉션(recipe_db_v2_exp)에 재임베딩 -> 동일 쿼리셋 plain 비교 -> 임시 컬렉션 삭제.
embed_text 순효과는 plain 검색에서 드러난다(smart 는 LLM 쿼리확장이 차이를 가림).

실행 (backend 디렉토리, 전용 venv):
  .venv\\Scripts\\python.exe scripts\\rag_ablation.py
경고: 1693건 재임베딩(LM Studio embed 호출 다수) — 수 분 소요 가능. recipe_db 무영향(임시 컬렉션만).
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]  # = backend/
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))  # rag_eval 동일 폴더 import
try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except Exception:
    pass
try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:
    pass

from app.rag.embedder import Embedder  # noqa: E402
from app.rag.indexer import COLLECTION_NAME, _sanitize_metadata, get_chroma_client  # noqa: E402
from app.rag.retriever import _decode_meta  # noqa: E402
from rag_eval import EVAL, _rank_of  # noqa: E402

V2_COL = "recipe_db_v2_exp"


def lean_embed_text(m: dict) -> str:
    """V2: 이름 + 전체재료 + 장르 (영양/시간/steps 제거 — 희석 최소)."""
    ings = ", ".join(i.get("name", "") for i in (m.get("ingredients") or []))
    return f"{m.get('name','')} 재료: {ings} 장르: {m.get('cuisine_type','기타')}"


async def _eval_plain(col, embedder, label: str) -> dict:
    p1 = p3 = 0
    rr = 0.0
    rows = []
    for q, expected, cat in EVAL:
        qv = await embedder.embed_query(q)
        res = col.query(query_embeddings=[qv], n_results=3)
        metas = (res.get("metadatas") or [[]])[0]
        docs = [_decode_meta(mt) for mt in metas]
        rank = _rank_of(docs, expected)
        p1 += rank == 1
        p3 += rank in (1, 2, 3)
        rr += (1.0 / rank) if rank else 0.0
        rows.append((cat, q, expected, docs[0].get("name", "-") if docs else "-", rank))
    n = len(EVAL)
    print(f"\n== {label} ==  P@1={p1}/{n}={p1/n:.0%}  P@3={p3}/{n}={p3/n:.0%}  MRR={rr/n:.3f}")
    for cat, q, exp, t1, rank in rows:
        mark = "OK" if rank == 1 else ("~ " if rank else "X ")
        print(f"  {mark} {cat:4} {q[:28]:28} -> {t1[:16]:16} (exp {exp}, rank {rank or '-'})")
    return {"P@1": p1 / n, "P@3": p3 / n, "MRR": rr / n}


async def main():
    emb = Embedder()
    client = get_chroma_client()
    v1 = client.get_collection(COLLECTION_NAME)
    print(f"V1 recipe_db: {v1.count()}건, sig={(v1.metadata or {}).get('embed_sig')}")

    got = v1.get(include=["metadatas"])
    metas = [_decode_meta(m) for m in got["metadatas"]]
    ids = got["ids"]
    texts = [lean_embed_text(m) for m in metas]
    print(f"V2 lean 재임베딩 {len(texts)}건 ...")
    vecs = []
    for i in range(0, len(texts), 64):
        vecs.extend(await emb.embed_documents(texts[i:i + 64]))

    try:
        client.delete_collection(V2_COL)
    except Exception:
        pass
    v2 = client.create_collection(V2_COL, metadata={"hnsw:space": "cosine"})
    for i in range(0, len(ids), 500):
        v2.add(ids=ids[i:i + 500], documents=texts[i:i + 500], embeddings=vecs[i:i + 500],
               metadatas=[_sanitize_metadata(m) for m in metas[i:i + 500]])

    r1 = await _eval_plain(v1, emb, "V1 현행 (재료+steps+영양+시간+장르)")
    r2 = await _eval_plain(v2, emb, "V2 lean (이름+재료+장르)")
    print("\n===== ablation 요약 (plain) =====")
    for k in ("P@1", "P@3", "MRR"):
        print(f"  {k}: V1 {r1[k]:.3f}  vs  V2 {r2[k]:.3f}  (d {r2[k]-r1[k]:+.3f})")

    client.delete_collection(V2_COL)
    print("\n임시 컬렉션 삭제됨 (recipe_db 무영향)")


if __name__ == "__main__":
    asyncio.run(main())
