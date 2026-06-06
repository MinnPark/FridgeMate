from app.config import settings
from app.graph.state import FridgeMateState
from app.rag.integration import search_sync, THEIR_STRATEGY
from app.rag.integration import retrieve_recipes
from app.tools.logging_tools import append_log


def choose_rag_strategy(query: str) -> str:
    """
    쿼리 길이 기반 RAG 전략 선택.

    integration._resolve_strategy() 가 이 함수를 lazy import 로 우선 호출한다.
    반드시 "HyDE" | "RAG-Fusion" | "Basic-RAG" 중 하나를 반환해야 한다.

    판단 기준 (integration.HYDE_THRESHOLD = config.hyde_query_length_threshold = 10):
      공백 제거 후 길이 < 10  →  "HyDE"      (짧은 재료 키워드)
      공백 제거 후 길이 >= 10 →  "RAG-Fusion" (복합 조건 쿼리)
    """
    q = query.strip().replace(" ", "")
    if len(q) < settings.hyde_query_length_threshold:
        return "HyDE"
    return "RAG-Fusion"


def retrieve_recipes(query: str, state: FridgeMateState) -> list[dict]:
    """실 RAG(bge-m3 임베딩 + HyDE/RAG-Fusion/RRF, recipe_db 1,693건)로 검색.

    전략 판정은 choose_rag_strategy. 실제 HyDE 가상문서/Fusion 멀티쿼리는
    app.rag.hyde / app.rag.rag_fusion 에서 LLM(서브모델)으로 생성됨
    (백엔드 로그 [RAG/HyDE] / [RAG/Fusion] 에서 실값 확인).
    trace 는 실제 검색 결과만 담는다 (프론트 AgentPipelinePanel 은 strategy 만 사용).
    """
    strategy = choose_rag_strategy(query)
    results, rag_trace = search_sync(query, strategy=THEIR_STRATEGY.get(strategy, "basic"))
    top = [r.get("name", "") for r in results[:5]]
    trace = {
        "strategy": strategy,
        "original_query": query,
        "engine": "rag(bge-m3)",
        "n_results": rag_trace.get("n_results"),
        "via": rag_trace.get("via"),
        "cache_hit": rag_trace.get("cache_hit"),
        "top": top,
    }
    # RAG 작동 가시화 (백엔드 로그 + trace -> 프론트 패널/LangSmith)
    print(f"[RAG] analyze : q={query!r} -> strategy={strategy} (engine=rag/bge-m3)", flush=True)
    print(f"[RAG] retrieve: via={trace.get('via')} n={len(results)} top={top}", flush=True)

    state["recipe_search_trace"] = trace
    return results
def _build_query(state: FridgeMateState) -> str:
    """
    pantry_items + user_input → RAG 검색 쿼리 생성.

    우선순위:
      1. expiry_priority == "high" 재료를 앞에 배치 (유통기한 임박 재료 우선 소비)
      2. priority 재료가 없으면 전체 재료 이름 사용
      3. user_input 을 뒤에 결합
      4. 둘 다 없으면 빈 문자열 반환

    예시:
      pantry=[두부(high), 계란(normal)], user_input="고단백 한식 식단 짜줘"
      → "두부 고단백 한식 식단 짜줘" (14자 → RAG-Fusion)

      pantry=[계란(normal)], user_input="식단"
      → "계란 식단" (5자 → HyDE)

      pantry=[두부(high)], user_input=""
      → "두부" (2자 → HyDE)
    """
    pantry_items = state.get("pantry_items") or []
    user_input = (state.get("user_input") or "").strip()

    # expiry_priority == "high" 재료 우선
    priority_names = [
        item["name"]
        for item in pantry_items
        if item.get("expiry_priority") == "high"
    ]

    # priority 재료가 없으면 전체 재료 이름 사용
    if not priority_names:
        priority_names = [item["name"] for item in pantry_items]

    parts: list[str] = []
    if priority_names:
        parts.append(" ".join(priority_names))
    if user_input:
        parts.append(user_input)

    return " ".join(parts)


def recipe_agent(state: FridgeMateState) -> FridgeMateState:
    """
    입력:  state["pantry_items"]        (pantry_agent 가 생성)
           state["user_input"]          (main.py ChatRequest.message)
    출력:  state["selected_recipes"]    (UI RecipesCard 용 + meal_agent 용)
           state["recipe_search_trace"] (retrieve_recipes 부수효과로 자동 설정)
           state["logs"]                (UI AgentPipelinePanel 용)
    """
    pantry_items = state.get("pantry_items") or []

    # pantry_items 없으면 조기 반환
    if not pantry_items:
        logs = append_log(
            state.get("logs"),
            node="recipe",
            event="skipped",
            reason="pantry_items 없음",
        )
        return {
            **state,
            "selected_recipes": [],
            "recipe_search_trace": {"strategy": "none", "original_query": ""},
            "logs": logs,
        }

    # 1. 검색 쿼리 생성
    query = _build_query(state)

    # 2. RAG 검색
    # retrieve_recipes 가 state["recipe_search_trace"] 를 직접 설정하는 부수효과 존재
    # → 반환 후 {**state} 에 recipe_search_trace 가 포함됨
    try:
        results = retrieve_recipes(query, state)
    except Exception as e:
        logs = append_log(
            state.get("logs"),
            node="recipe",
            event="rag_retrieval_failed",
            error=str(e),
        )
        return {
            **state,
            "selected_recipes": [],
            "recipe_search_trace": state.get("recipe_search_trace")
                or {"strategy": "error", "original_query": query},
            "logs": logs,
        }

    # 3. 상위 3개 선택
    selected = results[:3]

    # 4. 임박 재료 중 실제 레시피에 포함된 것 추적
    priority_items_used = [
        item["name"]
        for item in pantry_items
        if item.get("expiry_priority") == "high"
        and any(
            ing.get("name") == item["name"]
            for r in selected
            for ing in r.get("ingredients", [])
        )
    ]

    # 5. 로그 기록
    trace = state.get("recipe_search_trace") or {}
    logs = append_log(
        state.get("logs"),
        node="recipe",
        event="rag_retrieval_completed",
        result={
            "strategy": trace.get("strategy", ""),
            "original_query": query,
            "recipes_found": len(selected),
            "priority_items_used": priority_items_used,
        },
    )

    return {
        **state,
        "selected_recipes": selected,
        "logs": logs,
        # recipe_search_trace 는 retrieve_recipes 가 state 에 직접 설정했으므로
        # {**state} 에 이미 포함됨 → 별도 명시 불필요
    }
