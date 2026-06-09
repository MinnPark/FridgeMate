"""대규모 RAG 검색 성능 벤치마크 (100+ 쿼리) — PLAIN vs SMART.

평가셋 생성(코퍼스 기반, 정답이 실제 recipe_db 안):
  1) auto-ingredient : 코퍼스에서 레시피 N개 샘플 -> 그 레시피의 재료 상위 4개를 쿼리로,
                       정답 = 그 레시피 이름. (재료기반 의미검색 난이도)
  2) handcrafted     : scripts/rag_eval.py 의 16개(오타/묘사/구어) 합류.
정답 매칭은 '이름'(원 하네스와 동일). 동명 레시피는 같은 요리로 보고 hit 인정.

지표: P@1, P@3, Hit@5(=Recall@5, 단일정답), MRR — 전체 + 층화 + 95% Wilson 신뢰구간.
SMART 는 LLM(로컬 서브모델) 비결정 -> 1회치. 코퍼스 읽기만(재인덱싱 없음).

실행(backend, 전용 venv):
  .venv\\Scripts\\python.exe scripts\\rag_eval_bulk.py --mode both --n 110
  옵션: --mode plain|smart|both  --n <샘플 레시피수>  --smart-cap <SMART 쿼리 상한>  --seed 42
"""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import random
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
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

# 원 하네스 16개 (오타/묘사/구어)
HANDCRAFTED: list[tuple[str, str, str]] = [
    ("김치찌게", "김치찌개", "오타"), ("된장찌게", "된장찌개", "오타"),
    ("제육뽁음", "제육볶음", "오타"), ("비빔밤", "비빔밥", "오타"),
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


def _load_corpus() -> list[dict]:
    col = get_chroma_client().get_or_create_collection(
        COLLECTION_NAME, metadata={"hnsw:space": "cosine"})
    got = col.get(include=["metadatas"])
    out = []
    for rid, meta in zip(got["ids"], got["metadatas"]):
        ings = meta.get("ingredients")
        if isinstance(ings, str):
            try:
                ings = json.loads(ings)
            except Exception:
                ings = []
        out.append({"id": rid, "name": meta.get("name") or "", "ingredients": ings or []})
    return out, (col.metadata or {}).get("embed_sig"), col.count()


def _build_ingredient_queries(corpus: list[dict], n: int, seed: int) -> list[tuple[str, str, str]]:
    random.seed(seed)
    seen_names: set[str] = set()
    pool = []
    for r in corpus:
        nm = (r["name"] or "").strip()
        names = [i.get("name", "").strip() for i in r["ingredients"] if i.get("name")]
        if not nm or nm in seen_names or len(names) < 4:
            continue
        seen_names.add(nm)
        pool.append((nm, names))
    random.shuffle(pool)
    items = []
    for nm, names in pool[:n]:
        query = " ".join(names[:4])               # 재료 상위 4개 조합 쿼리
        items.append((query, nm, "재료조합"))
    return items


def _rank_of(docs: list[dict], expected_name: str) -> int:
    for i, d in enumerate(docs):
        if d.get("name") == expected_name:
            return i + 1
    return 0


def _wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = (z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / denom
    return (max(0.0, center - half), min(1.0, center + half))


async def _eval(search_fn, label: str, eval_set: list[tuple[str, str, str]], k: int = 5) -> dict:
    by_strat: dict[str, list[int]] = defaultdict(list)   # strat -> list of ranks
    for q, expected, strat in eval_set:
        docs = await search_fn(q, k=k)
        by_strat[strat].append(_rank_of(docs, expected))

    def metrics(ranks: list[int]) -> dict:
        n = len(ranks)
        p1 = sum(1 for r in ranks if r == 1)
        p3 = sum(1 for r in ranks if r in (1, 2, 3))
        h5 = sum(1 for r in ranks if r and r <= 5)
        rr = sum((1.0 / r) for r in ranks if r)
        return {"n": n, "P@1": p1 / n, "P@3": p3 / n, "Hit@5": h5 / n, "MRR": rr / n,
                "P@1_ci": _wilson(p1, n), "P@3_ci": _wilson(p3, n), "Hit@5_ci": _wilson(h5, n)}

    all_ranks = [r for rs in by_strat.values() for r in rs]
    res = {"overall": metrics(all_ranks), "by_strat": {s: metrics(rs) for s, rs in by_strat.items()}}
    print(f"\n===== {label}  (n={len(all_ranks)}) =====")
    o = res["overall"]
    print(f"  전체   P@1={o['P@1']:.1%}  P@3={o['P@3']:.1%}  Hit@5={o['Hit@5']:.1%}  MRR={o['MRR']:.3f}")
    print(f"         (95%CI P@3 {o['P@3_ci'][0]:.0%}~{o['P@3_ci'][1]:.0%})")
    for s, m in res["by_strat"].items():
        print(f"  [{s:6}] n={m['n']:3}  P@1={m['P@1']:.0%}  P@3={m['P@3']:.0%}  Hit@5={m['Hit@5']:.0%}  MRR={m['MRR']:.3f}")
    return res


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["plain", "smart", "both"], default="both")
    ap.add_argument("--n", type=int, default=110)
    ap.add_argument("--smart-cap", type=int, default=0, help="SMART 쿼리 상한(0=전체)")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    corpus, sig, count = _load_corpus()
    auto = _build_ingredient_queries(corpus, args.n, args.seed)
    eval_set = auto + HANDCRAFTED
    print(f"corpus: recipe_db {count}건 (embed_sig={sig})")
    print(f"평가셋: {len(eval_set)}쿼리 (재료조합 {len(auto)} + 수작업 {len(HANDCRAFTED)}) | seed={args.seed}")

    if args.mode in ("plain", "both"):
        await _eval(search_recipes, "PLAIN (순수 bge-m3 벡터)", eval_set)
    if args.mode in ("smart", "both"):
        s_set = eval_set if not args.smart_cap else eval_set[:args.smart_cap]
        await _eval(smart_search, "SMART (HyDE/RAG-Fusion+RRF)", s_set)


if __name__ == "__main__":
    asyncio.run(main())
