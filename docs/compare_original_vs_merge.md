# 원본(fridge-mate) vs 머지(FridgeMate-Merge) 비교 — by neocello-ku

> 2026-06-06. 무엇이 제대로 이식됐고 무엇이 스켈레톤/미이식인지 비교용.
> 결론 한 줄: **RAG 엔진은 풀 이식, 그래프/API/노트북은 머지 쪽이 단순(또는 스켈레톤).**

---

## A. 노트북 (RAG 실험) — 머지는 스켈레톤 (심화 필요)
| 단계 | 원본 fridge-mate | 머지 | 격차 |
|---|---|---|---|
| 01 수집 | 01_collection (7셀/3code, 소스2종+SKIP 로직) | 01_collect (3셀/2) | 얕음 |
| 02 정규화 | 02_normalize (8셀/4) | 02_normalize (2셀/1) | 얕음 |
| 03 임베딩 | 03_embedding (8셀/4) | 03_embed (2셀/1) | 얕음 |
| 04 인덱싱 | 04_indexing (8셀/4) | 04_index (2셀/1) | 얕음 |
| 05 검색 | 05_search_basic (8셀/4) | 05_search (2셀/1) | 얕음 |
| 06 고급 | 06_search_advanced (12셀/6) | 06_advanced (2셀/1) | 얕음 |
| 07 평가 | 07_quality_eval (8셀/4) | 07_eval (2셀/1) | 얕음 |
- **머지 노트북 = 동작 골격(셀 1~2개)만.** 원본은 단계별 설명+중간 산출물(data/lab)로 연결된 풀 파이프라인.
- **TODO: 머지 노트북을 원본 수준으로 심화** (설명 셀 + 중간 검증 + lab 산출물 체인).

## B. 그래프 (LangGraph) — 머지는 팀메이트 3노드
| | 원본 fridge-mate | 머지 FridgeMate-Merge |
|---|---|---|
| 파일 | `backend/graph.py:build_state_graph` | `backend/app/graph/orchestrator.py:build_graph` |
| 노드 | **11개** orchestrator->pantry->intake->meal_plan_composer->recipe->gap_calc->shopping_rank->judge<->reflect->cart->cooking_guide | **3개** supervisor(entry분기)->meal\|recipe\|shopping->shopping->END |
| 패턴 | Plan-Execute + **Reflexion 루프** + judge 조건분기 | supervisor 라우팅(단순) |
| Studio | (langgraph.json 등록 시) | **이게 Studio에 뜨는 것** (+ rag_agent 서브그래프) |
- **Studio 그래프가 "덜한" 이유 = 머지 그래프 자체가 팀메이트 3노드.** 우리 풀 v3 11노드는 원본에만 있고 미이식.

## C. 오케스트레이터 위치 (질문 답)
- **원본**: `backend/nodes/orchestrator.py` (`orchestrator_node`) — `backend/graph.py` 가 entry 로 배선. 그 뒤 pantry/intake/composer... 순차.
- **머지**: `backend/app/graph/orchestrator.py` — **여기 한 파일에** `supervisor_router`(LLM 라우팅+fallback) + `build_graph`(노드3 배선) 둘 다 있음. Studio의 `fridgemate` 그래프가 이 파일.

## D. 백엔드 API
| | 원본 8001 (`backend/main.py`) | 머지 8742 (`app/main.py`) |
|---|---|---|
| 엔드포인트 | /health, /api/compose, /api/run, /api/stream(SSE), /api/chat, /api/kpi | **/health, /chat** (2개) |
- 머지 Swagger에 /chat 하나뿐인 이유 = 머지 API 가 팀메이트 단순 버전.

## 결론 / 선택지
머지 = **팀메이트 단순 그래프(3노드)+API(/chat) + 우리 RAG 엔진(풀)**. 의도된 옵션1 결과.
- 더 가려면: (A) 풀 v3 그래프 이식 (B) 멀티 API 이식 (C) 노트북 심화 — 모두 추가 스코프.
