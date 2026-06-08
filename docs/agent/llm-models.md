# 에이전트 LLM 모델 가이드 — 어떤 노드가 어떤 모델로 도는가

> 작성 2026-06-08 · 에이전트별 LLM 티어 + 자연어->구조화(constraints/선호도) 파싱 위치/모델 정리.
> 모델 ID는 **환경변수로만** 참조(CLAUDE.md 2장) — 코드 하드코딩 금지. 기본값은 `_llm.py` PROVIDER_DEFAULT_MODELS.

## 0. 한 줄

큰 일(의도해석·생성·검증)은 **Claude(Sonnet/Opus)**, 작은 일(검색 보조 쿼리)은 **로컬 qwen-7b**로 나눠 쓴다.
자연어를 `constraints`/선호도 dict로 바꾸는 건 **intake 노드가 Sonnet(큰 모델)으로** 한다.

## 1. 티어 표 (코드 기준)

| 용도 | 노드 | provider / 모델 | env (`model_env`) |
|---|---|---|---|
| 자연어 파싱(선호도·요리목표·일정·식이) | `v3/nodes/intake.py` | LLM_PROVIDER + **claude-sonnet-4-6** | `ANTHROPIC_MODEL_DEFAULT` |
| 식단 구성·생성·요약 | meal/shopping/orchestrator | 동일 (Sonnet) | `ANTHROPIC_MODEL_DEFAULT` |
| 품질 검증(영양·예산·제약) | `v3/nodes/judge.py` | **claude-opus-4-7** | `ANTHROPIC_MODEL_JUDGE` |
| RAG 검색 보조쿼리(HyDE 가상문서/Fusion 멀티쿼리) | `rag/hyde.py`,`rag/rag_fusion.py` | **local qwen2.5-7b** (LM Studio) | `RAG_LLM_PROVIDER=local` |

- **LLM_PROVIDER**: `anthropic`(기본) | `openrouter` | `local`. 팀 합의는 오케스트레이션=OpenRouter(Claude).
- **RAG_LLM_PROVIDER**: 서브쿼리 전용(기본 `local`). 오케와 분리 — 작은 쿼리에 큰 모델 비용 안 쓰려고.
- **FRIDGEMATE_USE_LLM**: `true` 여야 실제 LLM 호출. 아니면 모든 노드가 휴리스틱/fallback(offline 동작).

## 1.5 로컬 모델 — LM Studio 에 여러 개, 골라 쓸 수 있음

로컬(LM Studio, 58 서버 `:1234`)엔 임베딩/챗 모델이 여러 개 올라가 있고 **그중 골라 쓴다**.
- **조회**: `GET {LMSTUDIO_BASE_URL}/models` (헤더 `Authorization: Bearer {LMSTUDIO_API_KEY}`)
- **전환**: 임베딩 -> `.env` 의 `EMBED_MODEL_LOCAL` / 챗 서브쿼리 -> `LOCAL_MODEL_DEFAULT` 에 모델 ID 기입

2026-06-08 기준 17개(바뀔 수 있음):
- **임베딩**: `text-embedding-bge-m3`(현재) · `text-embedding-kure-v1` · `text-embedding-nomic-embed-text-v1.5`
- **챗(작은->큰)**: `qwen2.5-0.5b-instruct` · `llama_3.2_1b...` · `google/gemma-4-e4b` · `qwen3-4b-toolcalling-codex` ·
  `qwen/qwen3-4b-thinking-2507` · `qwen2.5-7b-instruct`(현재 서브쿼리) · `deepseek/deepseek-r1-0528-qwen3-8b` ·
  `granite-3.0-8b-instruct` · `microsoft/phi-4` · `qwen/qwen3-14b` · `openai/gpt-oss-20b` ·
  `qwen/qwen3-coder-30b` · `google/gemma-4-31b` · `granite-docling-258m`

> 주의: 로컬 모델 ID 가 코드 기본값(`_llm.py` PROVIDER_DEFAULT_MODELS)에 하드코딩돼 있다.
> 모델을 바꾸려면 코드 수정 말고 `.env` 의 `LOCAL_MODEL_DEFAULT` 로 오버라이드 권장(CLAUDE.md "모델 ID 하드코딩 금지").

## 2. 자연어 -> constraints/선호도 파싱 (집중)

위치: `v3/nodes/intake.py` (진입 pantry 다음 두 번째 노드). **2단계**:

1. **휴리스틱**(`_heuristic_parse`) — 정규식/키워드, offline 즉시.
   "매콤"->spice_level, "X 빼/싫/말고"->dislikes, "주말"->schedule.days, "고단백/다이어트"->diet_goals.
2. **LLM 파싱**(`_llm_parse`) — `call_llm(system_prompt_name="intake", model_env="ANTHROPIC_MODEL_DEFAULT", max_tokens=400)`.
   구조화 JSON(cuisines/spice/dislikes/favorites/dish_goals/schedule/diet_goals) 반환. **실패하면 휴리스틱 결과만 사용.**

### 왜 큰 모델(Sonnet)인가
- 의도 해석/구조화 추출은 **정확도**가 검색 필터 품질을 좌우(잘못 뽑으면 엉뚱하게 거름).
- 반면 HyDE/Fusion 서브쿼리는 "검색 보조 텍스트 생성"이라 오류 허용도가 커서 **로컬 7b**로 충분(비용↓).
- Judge(Opus)는 영양/예산 **수치 검증** 전용 — 파싱엔 과하다(쓰지 않음).

### RAG 입출력 계약과의 연결
intake가 뽑은 구조화 결과가 RAG `constraints`로 흘러간다. RAG는 그 dict를 받아 **기계적으로 필터만**(자연어 재해석 안 함). 상세 계약/샘플: `docs/rag-io-contract.md`.

## 3. 주의 — `_llm.py` 이원화 (정리 대상)

머지 과정에서 LLM 모듈이 **두 곳으로 갈라짐**. 통일 필요:

| 파일 | 로컬 provider | 모델ID | 엔드포인트 | rag_subquery_provider |
|---|---|---|---|---|
| `app/rag/_llm.py` | `local` | qwen2.5-7b-instruct / qwen3-14b | LM Studio :1234 | 있음 |
| `app/v3/tools/llm.py` | `local-ollama` | qwen2.5:7b / qwen2.5:14b | Ollama :11434 | 없음 |

- `intake.py`는 `from app.rag._llm import call_llm` 사용(= LM Studio 쪽).
- provider명/모델ID/포트가 달라, `LLM_PROVIDER`/`LOCAL_MODEL_*`를 어느 쪽 기준으로 맞추느냐에 따라 동작이 갈린다. **하나로 합치는 게 안전**(별도 작업).

## 4. 관련 문서
- 입출력 계약: `docs/rag-io-contract.md`
- RAG LLM 티어링(서브쿼리): `docs/rag-llm-tiering.md`
- 에이전트별 가이드: `docs/agent/{pantry,recipe,meal,shopping}_agent.md`
