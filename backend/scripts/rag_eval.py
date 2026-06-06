"""RAG 쿼리 정확도 측정 — 오타/묘사/구어 쿼리를 일부러 비틀어 던져 기대 레시피 매칭.

precision@1, precision@3, MRR.
- plain : search_recipes (순수 bge-m3 벡터검색) — 임베딩 자체 정확도
- smart : smart_search (HyDE/RAG-Fusion 라우팅) — 고급 RAG 효과

실행 (backend 디렉토리에서, 전용 venv):
  .venv\\Scripts\\python.exe scripts\\rag_eval.py

주의: 기존 recipe_db(1,693) 를 읽기만 한다. 재인덱싱/wipe 없음.
SMART 는 LLM(서브모델) 비결정성으로 run 마다 변동 — 보고서 수치는 1회치 (docs/rag-experiment-report.md §1-1).
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]  # = backend/
sys.path.insert(0, str(ROOT))
try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except Exception:
    pass
try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:
    pass

from app.rag.indexer import COLLECTION_NAME, get_chroma_client  # noqa: E402
from app.rag.retriever import search_recipes  # noqa: E402
from app.rag.smart_search import smart_search  # noqa: E402

# (쿼리, 기대 요리, 카테고리) — 정타 아님. 일부러 비틀어 던진다.
EVAL: list[tuple[str, str, str]] = [
    ("김치찌게", "김치찌개", "오타"),
    ("된장찌게", "된장찌개", "오타"),
    ("제육뽁음", "제육볶음", "오타"),
    ("비빔밤", "비빔밥", "오타"),
    ("돼지고기랑 김치 넣고 끓인 국물요리", "김치찌개", "묘사"),
    ("매콤한 돼지고기 볶음 한식", "제육볶음", "묘사"),
    ("두부 들어간 매운 중국요리", "마파두부", "묘사"),
    ("닭이랑 감자 넣고 졸인 한식", "닭볶음탕", "묘사"),
    ("계란 풀어서 말아 부친 반찬", "계란말이", "묘사"),
    ("토마토 소스 들어간 스파게티", "토마토 파스타", "묘사"),
    ("밥에 나물이랑 고추장 넣고 비벼 먹는 거", "비빔밥", "묘사"),
    ("계란으로 밥 감싼 양식", "오므라이스", "묘사"),
    ("닭가슴살 채소 샐러드", "샐러드 보울", "묘사"),
    ("오늘 추운데 뜨끈한 돼지 김치 국물", "김치찌개", "구어"),
    ("애들 좋아하는 케첩 볶음밥 계란", "오므라이스", "구어"),
    ("된장 풀어 끓인 두부 찌개", "된장찌개", "구어"),
]


def _rank_of(docs: list[dict], expected: str) -> int:
    for i, d in enumerate(docs):
        if d.get("name") == expected:
            return i + 1  # 1-based
    return 0  # miss


async def _eval(search_fn, label: str) -> dict:
    p1 = p3 = 0
    rr = 0.0
    rows = []
    for q, expected, cat in EVAL:
        docs = await search_fn(q, k=3)
        rank = _rank_of(docs, expected)
        top1 = docs[0]["name"] if docs else "-"
        p1 += 1 if rank == 1 else 0
        p3 += 1 if rank in (1, 2, 3) else 0
        rr += (1.0 / rank) if rank else 0.0
        mark = "OK" if rank == 1 else ("~ " if rank else "X ")
        rows.append((mark, cat, q, expected, top1, rank))
    n = len(EVAL)
    print(f"\n===== {label} =====")
    print(f"{'':2} {'cat':4} {'query':32} {'expected':12} {'top1':12} rank")
    for mark, cat, q, exp, t1, rank in rows:
        print(f"{mark:2} {cat:4} {q[:32]:32} {exp:12} {t1:12} {rank or '-'}")
    print(f"  P@1={p1}/{n}={p1/n:.0%}  P@3={p3}/{n}={p3/n:.0%}  MRR={rr/n:.3f}")
    return {"P@1": p1 / n, "P@3": p3 / n, "MRR": rr / n}


async def main():
    col = get_chroma_client().get_or_create_collection(
        COLLECTION_NAME, metadata={"hnsw:space": "cosine"}
    )
    sig = (col.metadata or {}).get("embed_sig")
    print(f"corpus: recipe_db {col.count()}건 (embed_sig={sig})  쿼리 {len(EVAL)}개")
    plain = await _eval(search_recipes, "PLAIN  (순수 bge-m3 벡터)")
    smart = await _eval(smart_search, "SMART  (HyDE/RAG-Fusion, 서브모델 LLM)")
    print("\n===== 요약 =====")
    for k in ("P@1", "P@3", "MRR"):
        print(f"  {k}: plain {plain[k]:.3f}  ->  smart {smart[k]:.3f}  (d {smart[k]-plain[k]:+.3f})")


if __name__ == "__main__":
    asyncio.run(main())
