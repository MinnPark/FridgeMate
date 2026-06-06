"""RAG 전략 인스펙터 — 같은 쿼리를 Basic / HyDE / RAG-Fusion 으로 각각 강제 실행해
유사도(dist, 작을수록 가까움) / RRF점수 / 결과 차이를 나란히 본다.

라우팅(choose_rag_strategy)이 무엇을 고르든 상관없이 세 전략을 직접 태워 비교.
서브쿼리 LLM(HyDE 가상답변 / Fusion 멀티쿼리)은 RAG_LLM_PROVIDER(기본 local=LM Studio) 사용.

실행 (backend 디렉토리, 전용 venv):
  .venv\\Scripts\\python.exe scripts\\rag_inspect.py "된장찌개" "고단백 한식 다이어트 점심"
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

from app.rag._llm import current_provider, rag_subquery_provider, llm_enabled  # noqa: E402
from app.rag.hyde import hyde_search  # noqa: E402
from app.rag.rag_fusion import rag_fusion_search  # noqa: E402
from app.rag.retriever import search_recipes  # noqa: E402


async def inspect(query: str, k: int = 5):
    print(f"\n========== QUERY: {query!r} ==========")

    basic = await search_recipes(query, k=k)
    print("\n[BASIC-RAG] 순수 bge-m3 벡터 (dist=거리, 작을수록 유사)")
    for d in basic:
        print(f"   {d.get('name',''):<20} dist={round(d.get('distance',0),4)}  src={d.get('source')}")

    hyde = await hyde_search(query, k=k)
    print("\n[HyDE] LLM 가상답변 임베딩 후 검색")
    for d in hyde:
        print(f"   {d.get('name',''):<20} dist={round(d.get('distance',0),4)}  src={d.get('source')}")

    fusion = await rag_fusion_search(query, k=k)
    print("\n[RAG-Fusion] 멀티쿼리 4개 + RRF (rrf=점수, 클수록 상위)")
    for d in fusion:
        print(f"   {d.get('name',''):<20} rrf={d.get('_rrf_score')}  src={d.get('source')}")

    nb = {d.get("name") for d in basic}
    nh = {d.get("name") for d in hyde}
    nf = {d.get("name") for d in fusion}
    print("\n[차이 분석]")
    print(f"   3전략 공통    : {sorted(nb & nh & nf)}")
    print(f"   HyDE 만 잡음  : {sorted(nh - nb - nf)}")
    print(f"   Fusion 만 잡음: {sorted(nf - nb - nh)}")
    print(f"   Basic 만 잡음 : {sorted(nb - nh - nf)}")


async def main():
    print(f"오케스트레이션 provider={current_provider()} | 서브쿼리 provider={rag_subquery_provider()} "
          f"| 서브 enabled={llm_enabled(rag_subquery_provider())}")
    queries = sys.argv[1:] or ["된장찌개", "고단백 한식 다이어트 점심"]
    for q in queries:
        await inspect(q)


if __name__ == "__main__":
    asyncio.run(main())
