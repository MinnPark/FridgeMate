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
    pantry_items + user_input + excluded_ingredients → RAG 검색 쿼리 생성.

    우선순위:
      1. excluded_ingredients 를 pantry_items 에서 먼저 제거
      2. expiry_priority == "high" 재료를 앞에 배치
      3. priority 재료가 없으면 전체 재료 이름 사용
      4. user_input 을 뒤에 결합
      5. 둘 다 없으면 빈 문자열 반환
    """
    pantry_items = state.get("pantry_items") or []
    user_input   = (state.get("user_input") or "").strip()
    excluded     = (state.get("excluded_ingredients") or "").strip()

    # 제외 재료 set 생성
    excluded_names = {
        e.strip()
        for e in excluded.split(",")
        if e.strip()
    }

    # pantry에서 제외 재료 먼저 제거                    ← 핵심 변경
    filtered_pantry = [
        item for item in pantry_items
        if item.get("name", "").strip() not in excluded_names
    ]

    priority_names = [
        item["name"]
        for item in filtered_pantry
        if item.get("expiry_priority") == "high"
    ]

    if not priority_names:
        priority_names = [item["name"] for item in filtered_pantry]

    parts: list[str] = []
    if priority_names:
        parts.append(" ".join(priority_names))
    if user_input:
        parts.append(user_input)

    return " ".join(parts)


def _filter_excluded(recipes: list[dict], excluded_str: str) -> list[dict]:
    """
    excluded_str 에 포함된 재료가 들어간 레시피 제거

    규칙:
      - 쉼표(,) 구분으로 복수 재료 처리
      - 정확한 이름 매칭만 허용 ("닭" 이라고 해서 "닭가슴살" 제외 안 됨)
      - 필터 후 결과 0개면 필터 미적용 → 원본 반환 (fallback)
      - excluded_str 비어있으면 원본 그대로 반환

    예시:
      excluded_str = "닭가슴살"
      → ingredients 에 "닭가슴살" 포함된 레시피 제외

      excluded_str = "닭가슴살, 돼지고기"
      → 두 재료 중 하나라도 포함된 레시피 제외
    """
    if not excluded_str:
        return recipes

    excluded_names = {
        e.strip()
        for e in excluded_str.split(",")
        if e.strip()
    }

    filtered = []
    for r in recipes:
        # 1. ingredients 필드 검사 (정확한 이름 매칭)
        ingredient_names = {
            ing.get("name", "").strip()
            for ing in r.get("ingredients", [])
        }

        # 2. 레시피 이름 검사 (부분 포함 검사)      ← 추가
        recipe_name = r.get("name", "")

        # 둘 중 하나라도 걸리면 제외
        excluded_by_ingredient = bool(excluded_names & ingredient_names)
        excluded_by_name       = any(
            exc in recipe_name for exc in excluded_names
        )

        if excluded_by_ingredient or excluded_by_name:
            print(
                f"[recipe_agent] 제외: '{recipe_name}' "
                f"(ingredient={excluded_by_ingredient}, name={excluded_by_name})",
                flush=True,
            )
            continue

        filtered.append(r)

    # fallback: 필터 후 0개면 원본 반환
    if not filtered:
        print(
            f"[recipe_agent] _filter_excluded: 필터 후 0개 → fallback(원본 반환) "
            f"excluded={excluded_names}",
            flush=True,
        )
        return recipes

    print(
        f"[recipe_agent] _filter_excluded: {len(recipes)}개 → {len(filtered)}개 "
        f"excluded={excluded_names}",
        flush=True,
    )
    return filtered


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

    # 3. 제외 재료 필터링 후 상위 9개 선택                     ← 수정
    excluded_str = (state.get("excluded_ingredients") or "").strip()
    filtered     = _filter_excluded(results, excluded_str)
    selected     = filtered[:9]

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
            "strategy":           trace.get("strategy", ""),
            "original_query":     query,
            "recipes_found":      len(selected),
            "excluded":           excluded_str or None,              # ← 추가
            "priority_items_used": priority_items_used,
        },
    )

    return {
        **state,
        "selected_recipes": selected,
        "logs": logs,
    }
