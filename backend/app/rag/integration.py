"""RAG 통합 drop-in 어댑터 — 팀메이트 레포(FridgeMate-main) `retrieve_recipes()` seam 용.

목적: 우리 RAG(smart_search / HyDE / RAG-Fusion, recipe_db 1693, bge-m3) 출력을
팀메이트 레포가 기대하는 '레시피 dict 계약'으로 변환한다. 그쪽 recipe_agent.retrieve_recipes
*내부만* 이 facade 로 갈아끼우면 두 경로(recipe / meal)가 동시에 실검색을 쓴다.

────────────────────────────────────────────────────────────────────────
⚠️ 안전장치 / 가정 (코드 clone 전이라 '가정' 기반 — 착각 최소화용 표시)
────────────────────────────────────────────────────────────────────────
- TEAMMATE_CONTRACT_KEYS 는 **분석 보고서에서 추론**한 계약이다. 실제 코드 미확인.
  → clone 후 recipe_agent.py 의 mock 반환 dict 와 **반드시 대조**(아래 VERIFY).
- to_contract 는 우리 search_recipes 의 **실제** 출력(retriever.py 기준)을 매핑한다.
- 계약 위반(키 누락/타입 불일치)은 조용히 넘기지 않고 RuntimeError 로 **소리내어 실패**.
- 이 파일은 *순수 추가*. 기존 smart_search/retriever 를 건드리지 않는다.

VERIFY 체크리스트 (clone 후 통합 전에 한 줄씩 확인):
  [ ] recipe_agent.retrieve_recipes 실제 반환 dict 키 == TEAMMATE_CONTRACT_KEYS ?
  [ ] ingredients 항목 키가 (name, amount, unit) 맞나?      (우리 qty → amount 변환 중)
  [ ] nutrition 중첩 {calories, protein, carbs, fat} 맞나?  (우리 carb → carbs 변환 중)
  [ ] score / final_score 를 하류(meal dedup·프론트 정렬)가 어떻게 쓰나?
  [ ] state["recipe_search_trace"] 키 이름/구조 일치? (strategy·rewritten_queries·hyde_document)
  [ ] 포팅 후 import 경로: backend.rag.* → app.rag.* 로 조정
  [ ] 임베딩: 그쪽도 우리 bge-m3(LM Studio 58.148.250.103) + chroma(1693) 에 닿는가?
       (Cohere 아님! 보고서 §4-3 의 Cohere 가정은 폐기 — EMBED_PROVIDER=local)
"""
from __future__ import annotations

import asyncio
from collections import OrderedDict
from typing import Optional

from app.rag.smart_search import smart_search
from app.rag.retriever import search_recipes
from app.rag.hyde import hyde_search
from app.rag.rag_fusion import rag_fusion_search

# ✅ 2026-06-06 clone 후 VERIFY 완료 — 실제 recipe_agent.py 기준.
# 실제 mock 반환 계약 = 6키. citation_url/final_score 는 우리가 더 주는 보너스(그쪽 consumer 무시 OK).
REQUIRED_CONTRACT_KEYS = ("id", "name", "text", "ingredients", "nutrition", "score")
TEAMMATE_CONTRACT_KEYS = REQUIRED_CONTRACT_KEYS + ("citation_url", "final_score", "nutrition_available")
_INGREDIENT_KEYS = ("name", "amount", "unit")           # ✅ 실제 일치 (우리 qty→amount)
_NUTRITION_KEYS = ("calories", "protein", "carbs", "fat")  # ✅ 실제 일치 (우리 carb→carbs)

HYDE_THRESHOLD = 10  # choose_rag_strategy 와 동일 기준: 공백 제거 후 길이

# 그쪽 choose_rag_strategy 반환명 → 우리 search strategy 매핑 (실제 3전략 확인됨)
THEIR_STRATEGY = {"HyDE": "hyde", "RAG-Fusion": "rag_fusion", "Basic-RAG": "basic"}


def _score_of(d: dict) -> float:
    """우리 검색 결과 → 단일 정렬 점수. RAG-Fusion 은 _rrf_score, 그 외는 1-distance."""
    if isinstance(d.get("_rrf_score"), (int, float)):
        return round(float(d["_rrf_score"]), 5)
    dist = d.get("distance")
    # cosine distance 는 [0,2] 라 1-dist 가 음수가 될 수 있어 0 으로 클램프
    return round(max(0.0, 1.0 - float(dist)), 4) if isinstance(dist, (int, float)) else 0.0


def _normalize_scores(results: list[dict]) -> None:
    """전략별 score 스케일 차이(HyDE 1-dist ~0.7 / RAG-Fusion RRF ~0.02)를
    리스트 내 min-max 로 0..1 공통화한다. 끼니 누적·프론트 정렬에서 Fusion 결과가
    구조적으로 바닥에 깔리는 문제 방지. 리스트 내부 순위는 보존(상위=1.0).
    (튜닝 사유: docs/rag-tuning-changelog.md 변경2)"""
    if not results:
        return
    raw_scores = [r["score"] for r in results]
    lo, hi = min(raw_scores), max(raw_scores)
    span = (hi - lo) or 1.0
    for r in results:
        norm = round((r["score"] - lo) / span, 5)
        r["score"] = norm
        r["final_score"] = norm


def to_contract(d: dict) -> dict:
    """우리 search 결과 1건 → 팀메이트 retrieve_recipes 계약 dict.

    매핑 규칙(변환 지점 = 착각 포인트라 명시):
      qty → amount, carb → carbs, distance → score, source_url → citation_url.
    """
    s = _score_of(d)
    # amount 는 숫자 보장(미상=1). 기존 calculate_missing_ingredients 가 amount(None) 에
    # None-int 연산으로 crash 하므로(키 존재+값 None 이면 .get default 안 먹음) 경계에서 코어스.
    ingredients = [
        {"name": i.get("name", ""),
         "amount": i["qty"] if isinstance(i.get("qty"), (int, float)) else 1,
         "unit": i.get("unit", "")}
        for i in (d.get("ingredients") or [])
        if isinstance(i, dict)
    ]
    # 영양 '미수집'(농정원 mafra 537: 칼로리는 있고 P/C/F만 0%)을 응답에서 진짜 '0'과 구분한다.
    # 키/타입 계약은 유지(숫자) - consumer 호환. 식별은 nutrition_available 플래그로.
    def _num(v: object) -> float:
        return float(v) if isinstance(v, (int, float)) else 0.0
    cal, prot, carb, fat = (_num(d.get(k)) for k in ("calories", "protein", "carb", "fat"))
    # 매크로 미수집 식별: 칼로리는 있는데(>0) P/C/F가 전부 0이면 물리적 모순 -> 수집 안 된 것(mafra).
    # 진짜 0인 음식(칼로리도 0)은 미수집으로 보지 않는다 - '실제 0'을 '미상'으로 오판하던 버그 수정.
    macros_known = not (cal > 0 and prot == 0.0 and carb == 0.0 and fat == 0.0)
    item = {
        "id": str(d.get("id") or d.get("name") or ""),
        "name": d.get("name", ""),
        "text": " ".join(d.get("steps") or []) or d.get("name", ""),
        "ingredients": ingredients,
        "nutrition": {
            "calories": cal,
            "protein": prot,
            "carbs": carb,                 # 우리는 'carb', 그쪽은 'carbs'
            "fat": fat,
        },
        "nutrition_available": macros_known,       # False => 칼로리는 있는데 P/C/F 전부 0(미수집). 진짜 0(칼로리도 0)은 True
        "score": s,
        "citation_url": d.get("source_url", ""),  # 보고서 H6(citation 누락) 해소
        "final_score": s,                          # 제철/트렌드 부스팅 전까진 score 와 동일
    }
    _assert_contract(item)
    return item


def _assert_contract(item: dict) -> None:
    """계약 위반은 소리내어 실패 (조용한 오매칭 방지)."""
    missing = [k for k in REQUIRED_CONTRACT_KEYS if k not in item]
    if missing:
        raise RuntimeError(f"[rag.integration] 계약 키 누락: {missing} — to_contract 점검 필요")
    if not item["id"]:
        raise RuntimeError("[rag.integration] id 비어있음 — meal dedup 깨짐 위험")
    for ing in item["ingredients"]:
        if set(_INGREDIENT_KEYS) - set(ing):
            raise RuntimeError(f"[rag.integration] ingredient 키 불일치: {ing}")
    if set(_NUTRITION_KEYS) - set(item["nutrition"]):
        raise RuntimeError(f"[rag.integration] nutrition 키 불일치: {item['nutrition']}")


# ── meal 경로 폭주 방지 캐시 (보고서 §4-3: 끼니마다 HyDE LLM 호출 위험) ──────────
_CACHE: "OrderedDict[tuple, list[dict]]" = OrderedDict()
_CACHE_MAX = 256


def _cache_get(key: tuple) -> Optional[list[dict]]:
    if key in _CACHE:
        _CACHE.move_to_end(key)
        return _CACHE[key]
    return None


def _cache_put(key: tuple, val: list[dict]) -> None:
    _CACHE[key] = val
    _CACHE.move_to_end(key)
    while len(_CACHE) > _CACHE_MAX:
        _CACHE.popitem(last=False)


async def search(
    query: str,
    *,
    k: int = 10,
    strategy: Optional[str] = None,   # None=자동 / "basic"|"hyde"|"rag_fusion" 강제
    constraints: Optional[dict] = None,
    use_cache: bool = True,
) -> tuple[list[dict], dict]:
    """팀메이트 retrieve_recipes 가 부를 단일 진입점.

    반환: (계약형 레시피 list, trace dict). trace 는 그쪽 recipe_search_trace 로 넣으면 됨.
    strategy="basic" 은 meal 끼니 루프용(HyDE LLM 비용 차단). 미지정 시 길이로 자동(보고서 로직).
    """
    if not isinstance(query, str) or not query.strip():
        raise ValueError("[rag.integration] query 는 비어있지 않은 문자열이어야 함")
    constraints = constraints or {}
    chosen = strategy or ("hyde" if len(query.strip().replace(" ", "")) < HYDE_THRESHOLD else "rag_fusion")

    key = (query.strip(), k, chosen, constraints.get("cuisine_filter"), constraints.get("max_time"))
    if use_cache and (cached := _cache_get(key)) is not None:
        return cached, {"strategy": chosen, "cache_hit": True, "original_query": query}

    cf, mt = constraints.get("cuisine_filter"), constraints.get("max_time")
    if chosen == "basic":
        raw = await search_recipes(query, k=k, cuisine_filter=cf, max_time=mt)
    elif chosen == "hyde":
        raw = await hyde_search(query, k=k, cuisine_filter=cf, max_time=mt)
    elif chosen == "rag_fusion":
        raw = await rag_fusion_search(query, k=k, cuisine_filter=cf, max_time=mt)
    else:
        raw = await smart_search(query, k=k)  # 안전 폴백

    results = [to_contract(d) for d in raw]
    _normalize_scores(results)  # 전략 무관 0..1 공통 스케일 (점수 스케일 통일)
    trace = {
        "strategy": chosen,
        "original_query": query,
        "cache_hit": False,
        "n_results": len(results),
        "via": (raw[0].get("_via") if raw else None),
    }
    if use_cache:
        _cache_put(key, results)
    return results, trace


# ── sync 브리지 (그쪽 retrieve_recipes 는 def(동기), 우리 search 는 async) ──────────
# graph.invoke(동기) 경로라 실행 스레드에 루프 없음 → asyncio.run OK. 혹시 async 컨텍스트면 별도 스레드.
def _run_async(coro):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
        return ex.submit(lambda: asyncio.run(coro)).result()


def search_sync(query: str, *, k: int = 10, strategy: Optional[str] = None,
                constraints: Optional[dict] = None, use_cache: bool = True) -> tuple[list[dict], dict]:
    return _run_async(search(query, k=k, strategy=strategy, constraints=constraints, use_cache=use_cache))


def _resolve_strategy(query: str) -> str:
    """포팅 후 그쪽 choose_rag_strategy 우선(분기 정합성 보장), 없으면 우리 휴리스틱."""
    try:
        from app.agents.recipe_agent import choose_rag_strategy  # 포팅된 그쪽 함수
        return choose_rag_strategy(query)
    except Exception:
        return "HyDE" if len(query.replace(" ", "")) < HYDE_THRESHOLD else "RAG-Fusion"


def retrieve_recipes(query: str, state) -> list[dict]:
    """팀메이트 recipe_agent.retrieve_recipes 의 **동기 드롭인 대체**.

    그쪽 시그니처/부수효과 동일: state["recipe_search_trace"] 세팅 + 계약형 list 반환.
    실행부만 우리 RAG(실 bge-m3·HyDE·Fusion·RRF)로. 프론트 패널 위해 strategy 표기는 그쪽 명칭 유지.
    """
    their = _resolve_strategy(query)
    results, trace = search_sync(query, strategy=THEIR_STRATEGY.get(their, "basic"))
    trace["strategy"] = their  # HyDE / RAG-Fusion / Basic-RAG (프론트 AgentPipelinePanel 호환)
    # RAG 작동 가시화: 백엔드 로그 + trace(프론트 패널/LangSmith)에 단계 반영
    top = [r.get("name", "") for r in results[:5]]
    try:
        from app.rag.embedder import Embedder
        emb = f"{Embedder().provider}/{Embedder().model}"
    except Exception:
        emb = "?"
    trace.update({"embedder": emb, "top": top})
    print(f"[RAG] analyze: q={query!r} -> strategy={their} (embedder={emb})", flush=True)
    print(f"[RAG] retrieve: via={trace.get('via')} n={len(results)} top={top}", flush=True)
    state["recipe_search_trace"] = trace
    return results


if __name__ == "__main__":
    # 셀프 테스트 — 계약 형태 + 안전장치 동작 확인 (EMBED_PROVIDER=local 필요)
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    from dotenv import load_dotenv
    load_dotenv()

    async def _selftest():
        for q in ["된장찌개", "매콤한 돼지고기 볶음 한식"]:
            res, tr = await search(q, k=3)
            print(f"\nq={q!r} trace={tr}")
            for r in res:
                assert set(TEAMMATE_CONTRACT_KEYS) <= set(r), "계약 키 누락"
                print(f"  {r['name']:<16} score={r['score']} cite={r['citation_url'][:30]} "
                      f"ing={len(r['ingredients'])} kcal={r['nutrition']['calories']}")
        print("\nOK — 계약 통과")

    asyncio.run(_selftest())
