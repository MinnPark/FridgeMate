from app.config import settings
from app.graph.state import FridgeMateState
from app.prompts.recipe_prompts import HYDE_PROMPT, RAG_FUSION_PROMPT
from app.rag.integration import search_sync, THEIR_STRATEGY


MOCK_RECIPE_INDEX = [
    {
        "id": "recipe-doenjang-tofu",
        "name": "두부 된장찌개",
        "text": "두부와 애호박을 넣고 된장과 함께 끓이는 고단백 한식 찌개입니다.",
        "ingredients": [
            {"name": "두부", "amount": 300, "unit": "g"},
            {"name": "애호박", "amount": 1, "unit": "개"},
            {"name": "된장", "amount": 2, "unit": "tbsp"},
        ],
        "nutrition": {"calories": 420, "protein": 24, "carbs": 38, "fat": 12},
    },
    {
        "id": "recipe-egg-bibimbap",
        "name": "계란 채소 비빔밥",
        "text": "계란, 채소, 밥을 사용해 빠르게 만드는 균형식입니다.",
        "ingredients": [
            {"name": "계란", "amount": 2, "unit": "개"},
            {"name": "밥", "amount": 200, "unit": "g"},
            {"name": "시금치", "amount": 80, "unit": "g"},
        ],
        "nutrition": {"calories": 530, "protein": 22, "carbs": 72, "fat": 16},
    },
]


def choose_rag_strategy(query: str) -> str:
    if len(query.replace(" ", "")) < settings.hyde_query_length_threshold:
        return "HyDE"
    if any(token in query for token in ["고단백", "저칼로리", "한식", "점심", "예산"]):
        return "RAG-Fusion"
    return "Basic-RAG"


def generate_hyde_document(query: str) -> str:
    return f"{query}는 냉장고 재료를 활용해 만드는 한식 레시피이며 재료, 조리법, 영양 정보를 포함합니다."


def rewrite_queries_for_fusion(query: str) -> list[str]:
    return [
        query,
        f"{query} 단백질 풍부",
        f"{query} 냉장고 재료 활용",
        f"{query} 부족 재료 최소화",
    ]


def mock_vector_search(query: str) -> list[dict]:
    query_tokens = set(query.replace(",", " ").split())
    ranked = []
    for recipe in MOCK_RECIPE_INDEX:
        recipe_text = f"{recipe['name']} {recipe['text']}"
        score = sum(1 for token in query_tokens if token in recipe_text)
        ranked.append({**recipe, "score": score})
    return sorted(ranked, key=lambda item: item["score"], reverse=True)[:1]


def retrieve_recipes(query: str, state: FridgeMateState) -> list[dict]:
    """실 RAG(bge-m3 임베딩 + HyDE/RAG-Fusion/RRF, recipe_db 1,693건)로 검색.

    전략 판정(choose_rag_strategy)과 trace 포맷(프론트 AgentPipelinePanel 호환)은 유지,
    실행부만 mock_vector_search → app.rag.integration.search_sync 로 교체.
    반환 계약 동일: {id,name,text,ingredients[name,amount,unit],nutrition{...},score,(+citation_url)}.
    """
    strategy = choose_rag_strategy(query)
    trace = {"strategy": strategy, "original_query": query}

    if strategy == "HyDE":
        trace.update({"prompt": HYDE_PROMPT, "hyde_document": generate_hyde_document(query)})
    elif strategy == "RAG-Fusion":
        trace.update({"prompt": RAG_FUSION_PROMPT, "rewritten_queries": rewrite_queries_for_fusion(query)})

    results, rag_trace = search_sync(query, strategy=THEIR_STRATEGY.get(strategy, "basic"))
    top = [r.get("name", "") for r in results[:5]]
    trace.update({
        "engine": "rag(bge-m3)",
        "n_results": rag_trace.get("n_results"),
        "via": rag_trace.get("via"),
        "cache_hit": rag_trace.get("cache_hit"),
        "top": top,
    })
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
