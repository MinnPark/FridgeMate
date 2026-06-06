# RAG 이식 + 아키텍처 점검 (feature/rag-agent)

> 2026-06-06 · B파트(RAG). 신규 RAG 엔진을 이 레포(FridgeMate-main)에 이식한 PR 노트 + 구조 점검.
> 표기: **기존** = 이 레포에 원래 있던 코드 / **신규(RAG)** = 이식된 RAG 엔진.

---

## 1. 이 PR이 한 일 (RAG 이식, 옵션1 = 모듈 포팅)

- **단일 seam = `app/agents/recipe_agent.py:retrieve_recipes`** 만 교체. recipe/meal 두 경로가 이 함수를 공유하므로 한 곳만 갈아끼우면 둘 다 실 RAG 사용.
- 기존 mock(`MOCK_RECIPE_INDEX`, `mock_vector_search`) -> 신규 RAG: bge-m3 임베딩 + ChromaDB recipe_db(1,693건) + HyDE / RAG-Fusion / RRF + 개인화 boost.
- 기존 `choose_rag_strategy`(전략 판정, 10자 임계)와 `recipe_search_trace` 포맷(프론트 AgentPipelinePanel 호환)은 유지. 실행부만 교체.

### 이식 구성요소


| 위치                          | 내용                                                                                                                                                                                   |
| --------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `app/rag/`                  | RAG 엔진 자기완결 패키지 (embedder, indexer, retriever, hyde, rag_fusion, smart_search, preference_store, agent, integration) + `_llm`(LLM 추상) + `_normalize` + `data/`(fetch_*) + `prompts/` |
| `app/rag/integration.py`    | 통합 어댑터: 신규 출력 -> 기존 계약(`to_contract`), async `search` + sync `search_sync`/`retrieve_recipes`(브리지), 전략매핑, 계약위반 시 RuntimeError                                                        |
| `scripts/ingest_recipes.py` | 사전임베딩(멀티소스: 식약처+농정원+seed) -> recipe_db 증분 upsert                                                                                                                                     |
| `data/chroma/`              | 사전임베딩 산출물(recipe_db 1,693). 바로 서빙되게 동봉                                                                                                                                               |
| `.env.example`              | RAG env (EMBED_PROVIDER=local, LMSTUDIO_*, EMBED_SIG, OPENROUTER_*, 데이터키)                                                                                                            |


### 반환 계약 (기존 코드 대조 완료)

`{id, name, text, ingredients[{name,amount,unit}], nutrition{calories,protein,carbs,fat}, score}` (+ citation_url, final_score 보너스). 신규 내부값(qty/carb/distance/source_url)을 어댑터가 기존 계약으로 변환.

### sync/async

- **기존 그래프 = 동기**(graph.invoke), **신규 RAG = async**. -> `retrieve_recipes`는 sync 브리지(asyncio.run, RAG 내부 병렬 보존 = 다운그레이드 아님).
- 정석 업그레이드 = 기존 그래프를 async 전환(ainvoke/노드/main). 별도 합의 항목으로 분리.

### env

- `app/rag/__init__.py`가 import 시 load_dotenv() 자동 호출(자기완결). 전체 앱 .env 적용은 후속.

---

## 2. 아키텍처 점검 (학습용, 솔직 평가)

신규 RAG(소스: fridge-mate) 기준. LangGraph 정석을 잘 따르고 평균 이상. 최첨단은 아니나 견고. (기존 레포는 더 단순/초기 단계)


| 영역        | 신규 RAG 현재                                                     | 평가                           | 합리적 업그레이드                                      |
| --------- | ------------------------------------------------------------- | ---------------------------- | ---------------------------------------------- |
| State     | TypedDict + 일부 reducer                                        | 정석. nested는 dict[str,Any] 잔존 | 중첩 typed sub-model화                            |
| Graph     | StateGraph + 조건부엣지(judge<->reflect) + checkpointer 분기 + 서브그래프 | 상위권(Plan-Execute-Reflexion)  | async 노드, interrupt 정식화                        |
| Embedding | provider 추상 + embed_sig 벡터공간 가드 + 배치/async                    | 평균 이상(가드 견고)                 | 임베딩 캐시 상시화                                     |
| Retrieval | HyDE + RAG-Fusion+RRF + 라우팅 + boost                           | 고급RAG 다수 보유                  | (1)메타데이터 pre-filter (2)reranker (3)hybrid BM25 |
| Tools     | 함수형 + llm 추상                                                  | 견고(결정적 오케스트레이션)              | 필요시 정식 function-calling                        |
| 관측        | kpi + LangSmith 훅                                             | 양호                           | LangGraph Studio(langgraph.json) 살리기           |


### 효과 큰 업그레이드 3 (rewrite 아님)

1. Retrieval: 메타데이터 pre-filter 연결 + reranker (RAG 품질 직접 상승, 현재 가장 약한 고리)
2. 데이터 1만건+ (실험 리포트가 보인 커버리지 한계 — 외부채널 추가)
3. async 그래프 일관성

### 실험 근거 (요약)

- 1,693 코퍼스: PLAIN P@1 50% -> SMART(HyDE/Fusion+LLM) P@1 75% (+25%p). LLM 고급RAG가 진짜 레버.
- embed_text ablation(현행 vs lean): 집계 동일 -> 미세조정 효과 0, 현행 유지. (상세: 소스레포 `docs/rag_experiment_report.md`)

---

## 3. 후속 (오늘 범위 밖)

- 전체 앱 .env 적용 / 노트북 실험폴더(notebooks/) 이식 / 도커 서빙 / LangGraph Studio + LangSmith / 메타필터 + reranker / 데이터 1만건+.

