# recipe_agent.py 개발 문서

> 작성일: 2026-06-06  
> 작성자: 전영주
> 관련 파일: `app/agents/recipe_agent.py`

---

## 1. 역할 요약

`recipe_agent`는 **냉장고 재료 기반 레시피 검색 에이전트**다.  
`pantry_agent`가 분석한 재료 정보를 받아 RAG(검색 증강 생성)로 최적의 레시피를 찾아 반환한다.

```
pantry_agent
    └─ state["pantry_items"]
              ↓
        recipe_agent          ← 이 파일
              ↓
    state["selected_recipes"]
    state["recipe_search_trace"]
    state["logs"]
```

---

## 2. 전체 실행 흐름

```
recipe_agent(state)
    │
    ├─ pantry_items 없음?  →  조기 반환 (selected_recipes: [])
    │
    ├─ 1. _build_query(state)
    │       └─ priority(high) 재료 + user_input 결합 → 검색 쿼리
    │
    ├─ 2. retrieve_recipes(query, state)          ← integration.py
    │       ├─ _resolve_strategy(query)
    │       │       └─ choose_rag_strategy(query) ← recipe_agent.py (lazy import)
    │       ├─ search_sync(query, strategy=...)   ← ChromaDB 실검색
    │       └─ state["recipe_search_trace"] 자동 설정 (부수효과)
    │
    ├─ 3. results[:3]  →  상위 3개 선택
    │
    ├─ 4. priority_items_used 추적
    │       └─ 임박 재료 중 실제 레시피에 포함된 것만 기록
    │
    └─ 5. append_log() → state["logs"] 업데이트
```

---

## 3. 함수별 상세 설명

### 3-1. `choose_rag_strategy(query: str) -> str`

**역할**: 쿼리 길이 기반으로 RAG 전략을 선택한다.

> ⚠️ `integration._resolve_strategy()`가 이 함수를 **lazy import**로 호출한다.  
> 반드시 `"HyDE"` | `"RAG-Fusion"` | `"Basic-RAG"` 중 하나를 반환해야 한다.

**판단 기준** (`config.hyde_query_length_threshold = 10`):

| 조건 | 전략 | 설명 |
|------|------|------|
| 공백 제거 후 길이 `< 10` | `HyDE` | 짧은 재료 키워드 → 가상 문서 생성 후 검색 |
| 공백 제거 후 길이 `>= 10` | `RAG-Fusion` | 복합 조건 → 다각도 쿼리 생성 후 RRF 병합 |

**단계별 예시**:

```
입력 쿼리                              공백제거 길이  전략
─────────────────────────────────────────────────────────
"두부"                                 2자           HyDE
"계란 두부"                             4자           HyDE       ← 공백 제거 후 계산
"두부 고단백 한식"                       7자           HyDE
"두부브로콜리계란닭가"                    10자          RAG-Fusion
"닭가슴살 브로콜리 고단백 저탄수 식단 짜줘" 19자          RAG-Fusion
```

**RAG 전략 비교**:

| 전략 | 동작 방식 | 적합한 입력 |
|------|----------|-----------|
| `HyDE` | LLM으로 가상 레시피 문서 생성 → 임베딩 → ChromaDB 검색 | 재료 이름만 있는 짧은 쿼리 |
| `RAG-Fusion` | 4가지 관점 쿼리 생성 → 각각 검색 → RRF 점수 병합 | 영양/시간/인원 등 복합 조건 |

---

### 3-2. `_build_query(state: FridgeMateState) -> str`

**역할**: `pantry_items` + `user_input`을 결합해 RAG 검색 쿼리를 만든다.

**우선순위 규칙**:
1. `expiry_priority == "high"` 재료를 **앞에** 배치 (유통기한 임박 재료 우선 소비)
2. `high` 재료가 없으면 **전체** 재료 이름 사용
3. `user_input`을 **뒤에** 결합
4. 둘 다 없으면 **빈 문자열** 반환

**단계별 예시**:

#### 케이스 1: priority 재료 있음 (오늘: 2026-06-06)

```
입력 pantry_items:
  닭가슴살  expiry_priority="normal"  (2026-06-10, D+4)
  계란      expiry_priority="high"    (2026-06-07, D+1)  ← 임박
  브로콜리  expiry_priority="high"    (2026-06-08, D+2)  ← 임박
  두부      expiry_priority="high"    (2026-06-06, D+0)  ← 임박

입력 user_input:
  "냉장고에 닭가슴살, 계란, 브로콜리, 두부 있어. 고단백 저탄수. 2인분... 식단 짜줘"

처리 과정:
  priority_names = ["계란", "브로콜리", "두부"]   ← high 재료만
  parts = ["계란 브로콜리 두부", "냉장고에 ..."]

생성된 쿼리:
  "계란 브로콜리 두부 냉장고에 닭가슴살, 계란, 브로콜리, 두부 있어. 고단백 저탄수. 2인분... 식단 짜줘"
  → 공백제거 길이: 50자+ → RAG-Fusion 선택
```

#### 케이스 2: priority 재료 없음 (전체 폴백)

```
입력 pantry_items:
  닭가슴살  expiry_priority="normal"
  계란      expiry_priority="normal"

입력 user_input:
  "고단백 저탄수 식단 짜줘"

처리 과정:
  priority_names = []                 ← high 없음
  priority_names = ["닭가슴살", "계란"] ← 전체 폴백
  parts = ["닭가슴살 계란", "고단백 저탄수 식단 짜줘"]

생성된 쿼리:
  "닭가슴살 계란 고단백 저탄수 식단 짜줘"
  → 공백제거 길이: 17자 → RAG-Fusion 선택
```

#### 케이스 3: pantry_items 없음

```
입력 pantry_items: []
입력 user_input:   "식단 짜줘"

처리 과정:
  priority_names = []
  parts = ["식단 짜줘"]    ← user_input만

생성된 쿼리: "식단 짜줘"
```

---

### 3-3. `recipe_agent(state: FridgeMateState) -> FridgeMateState`

**역할**: 전체 레시피 검색 파이프라인을 실행하는 메인 함수.

#### Input (state 필드)

| 필드 | 타입 | 출처 | 설명 |
|------|------|------|------|
| `pantry_items` | `list[dict]` | `pantry_agent` | 재료 + expiry_priority 포함 |
| `user_input` | `str` | `main.py ChatRequest.message` | `chatAdapter.ts`가 생성한 자연어 |
| `logs` | `list[dict]` | `pantry_agent` | 기존 파이프라인 로그 |

#### Output (state 필드)

| 필드 | 타입 | 설명 |
|------|------|------|
| `selected_recipes` | `list[dict]` | 상위 3개 레시피 (BackendRecipe 계약) |
| `recipe_search_trace` | `dict` | 검색 전략/결과 메타데이터 |
| `logs` | `list[dict]` | 파이프라인 로그 추가 |

#### `selected_recipes` 각 항목 구조

```json
{
  "id": "tofu-egg-soup",
  "name": "두부 계란국",
  "text": "유통기한 임박 두부와 계란으로 만드는 고단백 한식",
  "ingredients": [
    {"name": "두부",   "amount": 300, "unit": "g"},
    {"name": "계란",   "amount": 2,   "unit": "개"},
    {"name": "대파",   "amount": 1,   "unit": "대"}
  ],
  "nutrition": {
    "calories": 180,
    "protein": 16,
    "carbs": 8,
    "fat": 9
  },
  "score": 0.91,
  "citation_url": "https://...",
  "final_score": 0.91
}
```

> ⚠️ `carbs` (복수형) 주의 — ChromaDB 원본은 `carb`이지만 `integration.to_contract()`가 변환함

#### `recipe_search_trace` 구조

```json
{
  "strategy": "RAG-Fusion",
  "original_query": "계란 브로콜리 두부 냉장고에...",
  "cache_hit": false,
  "n_results": 3,
  "via": "rag_fusion",
  "embedder": "local/bge-m3",
  "top": ["두부 계란국", "브로콜리 달걀볶음", "순두부찌개"]
}
```

#### `logs` 추가 항목

```json
{
  "node": "recipe",
  "event": "rag_retrieval_completed",
  "result": {
    "strategy": "RAG-Fusion",
    "original_query": "계란 브로콜리 두부...",
    "recipes_found": 3,
    "priority_items_used": ["계란", "두부"]
  }
}
```

---

## 4. 예외 처리

| 케이스 | 동작 |
|--------|------|
| `pantry_items` 없음 | 조기 반환. `selected_recipes=[]`, `log.event="skipped"` |
| ChromaDB 연결 실패 등 예외 | `selected_recipes=[]`, `log.event="rag_retrieval_failed"`, `error=str(e)` |

---

## 5. 의존성 구조

```
recipe_agent.py
    ├── app.config.Settings
    │       └── hyde_query_length_threshold = 10
    │
    ├── app.graph.state.FridgeMateState
    │       └── pantry_items, user_input, logs, selected_recipes,
    │           recipe_search_trace
    │
    ├── app.rag.integration.retrieve_recipes()
    │       ├── _resolve_strategy()
    │       │       └── choose_rag_strategy()  ← lazy import (이 파일)
    │       ├── search_sync()
    │       │       ├── hyde_search()          ← app.rag.hyde
    │       │       └── rag_fusion_search()    ← app.rag.rag_fusion
    │       └── to_contract()                  ← carb→carbs, qty→amount 변환
    │
    └── app.tools.logging_tools.append_log()
```

---

## 6. 관련 파일

| 파일 | 역할 |
|------|------|
| `app/rag/integration.py` | RAG 통합 어댑터. `retrieve_recipes()`, `search_sync()`, `to_contract()` |
| `app/rag/smart_search.py` | 쿼리 길이 기반 전략 자동 선택 |
| `app/rag/hyde.py` | HyDE 검색 구현 |
| `app/rag/rag_fusion.py` | RAG-Fusion + RRF 병합 구현 |
| `app/rag/retriever.py` | ChromaDB 기본 검색 |
| `app/graph/state.py` | `FridgeMateState` TypedDict 정의 |
| `app/config.py` | `hyde_query_length_threshold = 10` |
| `frontend/.../chatAdapter.ts` | `BackendRecipe` 계약 소비 |

---

## 7. 테스트 실행

```powershell
# backend/ 디렉토리에서 실행
cd D:\07.Coding\ku_agent\FridgeMate\backend
python tests/test_recipe_agent.py
```

**테스트 항목**:

| STEP | 테스트 내용 | 통과 조건 |
|------|------------|----------|
| 1 | `choose_rag_strategy()` 전략 선택 | 5개 케이스 모두 정확한 전략 반환 |
| 2 | `pantry_agent()` priority 재료 식별 | 계란/브로콜리/두부 → `high` |
| 3 | `_build_query()` priority 재료 있음 | 쿼리 앞부분에 priority 재료 포함 |
| 4 | `_build_query()` priority 재료 없음 | 전체 재료 이름 포함 |
| 5 | `_build_query()` pantry 없음 | `user_input` 그대로 반환 |
| 6 | `recipe_agent()` 정상 실행 | 레시피 1~3개 + 계약 키 통과 |
| 7 | `recipe_agent()` 조기 반환 | `selected_recipes=[]` + `log.event=