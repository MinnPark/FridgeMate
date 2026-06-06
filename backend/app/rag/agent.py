"""RAG 에이전트 — 독립 실행 가능한 LangGraph 서브그래프.

지금까지 RAG 는 메인 그래프(the main graph) 안에서 함수(smart_search→hyde/fusion)로
흩어져 호출됐다. 이를 **단일 에이전트**로 분리: 자체 state + 내부 오케스트레이션.

내부 흐름:
  analyze(쿼리 길이/제약 분석 → 라우팅)
    ├─[<10자]──→ hyde      (가상문서 임베딩 검색)
    └─[복합조건]→ rag_fusion (멀티쿼리 + RRF)
                      └→ boost(user_preference 개인화 re-rank) → END

- 메인 그래프와 독립 → LangGraph Studio 에서 'rag_agent' 단독 기동/디버깅 가능.
- 서브그래프로 메인에 임베드도 가능 (compile 결과를 노드로 add).
- FridgeMateState 와 분리된 RagState 사용 → 스키마 계약(§1.1) 영향 없음.

docs/data_architecture.md · CLAUDE.md §5b.
"""
from __future__ import annotations

import operator
from typing import Annotated, NotRequired, TypedDict

from langgraph.graph import END, START, StateGraph

from app.rag.hyde import hyde_search
from app.rag.preference_store import boost_by_preference
from app.rag.rag_fusion import rag_fusion_search

HYDE_THRESHOLD = 10


class RagState(TypedDict):
    # 입력
    query: str
    k: NotRequired[int]
    constraints: NotRequired[dict]      # {"cuisine_filter": str, "max_time": int}
    user_id: NotRequired[str]           # 있으면 개인화 boost
    # 내부/출력
    route: NotRequired[str]             # "hyde" | "rag_fusion"
    results: NotRequired[list[dict]]
    trace: Annotated[list[str], operator.add]   # 오케스트레이션 로그


def _k(state: RagState) -> int:
    return int(state.get("k") or 3)


async def analyze_node(state: RagState) -> dict:
    q = (state.get("query") or "").strip()
    route = "hyde" if 0 < len(q) < HYDE_THRESHOLD else "rag_fusion"
    return {"route": route, "trace": [f"analyze: len={len(q)} → {route}"]}


def _route(state: RagState) -> str:
    return state.get("route") or "rag_fusion"


async def hyde_node(state: RagState) -> dict:
    c = state.get("constraints") or {}
    docs = await hyde_search(state["query"], k=_k(state),
                             cuisine_filter=c.get("cuisine_filter"), max_time=c.get("max_time"))
    return {"results": docs, "trace": [f"hyde: {len(docs)} hits"]}


async def fusion_node(state: RagState) -> dict:
    c = state.get("constraints") or {}
    docs = await rag_fusion_search(state["query"], k=_k(state),
                                   cuisine_filter=c.get("cuisine_filter"), max_time=c.get("max_time"))
    return {"results": docs, "trace": [f"rag_fusion: {len(docs)} hits"]}


async def boost_node(state: RagState) -> dict:
    user_id = state.get("user_id")
    docs = state.get("results") or []
    if not user_id or not docs:
        return {"trace": ["boost: skip (개인화 이력 없음)"]}
    boosted = await boost_by_preference(user_id, docs, k=_k(state))
    return {"results": boosted, "trace": [f"boost: user_preference({user_id}) 재정렬"]}


def build_rag_graph() -> StateGraph:
    g = StateGraph(RagState)
    g.add_node("analyze", analyze_node)
    g.add_node("hyde", hyde_node)
    g.add_node("rag_fusion", fusion_node)
    g.add_node("boost", boost_node)

    g.add_edge(START, "analyze")
    g.add_conditional_edges("analyze", _route, {"hyde": "hyde", "rag_fusion": "rag_fusion"})
    g.add_edge("hyde", "boost")
    g.add_edge("rag_fusion", "boost")
    g.add_edge("boost", END)
    return g


def compile_rag_graph():
    return build_rag_graph().compile()
