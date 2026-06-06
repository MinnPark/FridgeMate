from app.config import settings
from app.graph.state import FridgeMateState
from app.rag.integration import search_sync, THEIR_STRATEGY


def choose_rag_strategy(query: str) -> str:
    if len(query.replace(" ", "")) < settings.hyde_query_length_threshold:
        return "HyDE"
    if any(token in query for token in ["고단백", "저칼로리", "한식", "점심", "예산"]):
        return "RAG-Fusion"
    return "Basic-RAG"


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


def recipe_agent(state: FridgeMateState) -> FridgeMateState:
    recipes = retrieve_recipes(state.get("user_input", ""), state)
    return {
        **state,
        "selected_recipes": recipes,
        "logs": state.get("logs", [])
        + [
            {
                "node": "recipe",
                "event": "rag_retrieval_completed",
                "trace": state.get("recipe_search_trace", {}),
            }
        ],
    }
