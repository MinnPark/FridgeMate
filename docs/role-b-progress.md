# 역할 B (RAG / VectorDB) 진행 상황

> 작성자: **neocello-ku** · 브랜치 `feature/recipe-rag_agent`

## 산출물 (`backend/app/rag/`, `scripts/`, `data/chroma/`)
- 실 RAG 엔진 이식: bge-m3 임베딩 + ChromaDB recipe_db(1,693건) + HyDE / RAG-Fusion / RRF + 개인화 boost
- 사전임베딩: `scripts/ingest_recipes.py` (멀티소스 식약처 1146 + 농정원 537 + seed 10 -> recipe_db 증분 upsert)
- 산출물 동봉: `data/chroma/` (recipe_db 1,693, embed_sig=bge-m3-1024) — 클론 즉시 검색 가능
- 통합 어댑터: `app/rag/integration.py` (신규 출력 -> 기존 계약 변환 + 동기 브리지)

## 기존(레포) 연동
- 방식: **단일 seam** `app/agents/recipe_agent.py:retrieve_recipes` 만 교체. recipe/meal 두 경로 동시 적용.
- 기존 `choose_rag_strategy`(10자 임계) / `recipe_search_trace` 포맷 유지(프론트 AgentPipelinePanel 호환).
- 반환 계약 동일: `{id,name,text,ingredients[name,amount,unit],nutrition{...},score}` (+citation_url, final_score 보너스).
- 기존 그래프=동기(graph.invoke) -> `retrieve_recipes`는 sync 브리지(asyncio.run, RAG 내부 병렬 보존 = 다운그레이드 아님).
- 상세: [architecture_review.md](architecture_review.md)

## 현재 실제 동작 vs 미제공
- **동작(검증)**: `app.main` import/부팅 OK(RAG 통합 동시 로드) · `retrieve_recipes` e2e(고단백 한식 -> 닭가슴살 요리, citation 포함) · 1,693 코퍼스 SMART P@1 75%.
- **구동 조건**: `backend/.env` 에 `LMSTUDIO_API_KEY`(필수) + `OPENROUTER_API_KEY`(권장) 채워야 함. `.env.example` 풀 템플릿 제공.
- **미제공(후속)**: 메타데이터 pre-filter, reranker, 데이터 1만건+, 전체 앱 .env 적용, 노트북 실험폴더, 도커.

## 실험 (요약)
- PLAIN P@1 50% -> SMART(HyDE/Fusion+LLM) 75% (+25%p). embed_text ablation: 현행 vs lean 동일 -> LLM 이 진짜 레버.
- 상세: [rag-experiment-report.md](rag-experiment-report.md)

## 다음 협의
- 그래프 async 전환(ainvoke/노드/main) = 기존 그래프 소유자와 합의 항목.
- shopping/cart 실연결(Naver/Coupang 키)은 RAG 밖(타 역할).

> 참고: 브랜치 전용 README [../README_RAG_neocello-ku.md](../README_RAG_neocello-ku.md) (구동법 포함).
