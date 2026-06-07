# RAG 입출력 계약 — 에이전트 <-> RAG (구현 명세)

> 작성 2026-06-08 · B파트(RAG) · 영양/재료/시간/장르 **필터 동시검색** 구현을 위한 입출력 계약 고정용.
> 목적: 에이전트가 RAG로 **무엇을 던지고(query + constraints)**, RAG가 **무엇을 돌려주는지(계약 dict)** 를 샘플로 못 박아 구현이 바로 가능하게 한다.

## 0. 한 줄

지금은 **자연어 query 문자열 하나만** 오가고 필터는 배선이 안 돼 사실상 **벡터 유사도 검색만** 동작한다. 영양/재료/시간/장르로 **정확히 거르려면** `constraints` 계약을 확정하고 배선해야 한다. 데이터는 식약처 1,146건(영양 완비)이 이미 준비돼 있다.

---

## ★ 전체 흐름 한눈에 (에이전트 -> RAG -> 응답 -> 다시 에이전트)

```
[사용자 자연어]  예: "고단백 한식, 계란 빼고 30분 안에"
   |
   v  (1) intake 노드 = LLM dict 파싱        [app/v3/nodes/intake.py]
   |       휴리스틱(정규식/키워드) + LLM(claude-sonnet-4-6, system prompt "intake")
   |       => 구조화 dict (이게 핵심 산출물):
   |          {
   |            "preferences": {"cuisines":["한식"], "spice_level":2,
   |                            "dislikes":["계란"], "favorites":[...]},
   |            "dish_goals": ["닭가슴살 요리"],
   |            "schedule":  {"days":["토","일"], "meals":["저녁"]},
   |            "diet_goals": ["고단백"]
   |          }
   |       * LLM 실패/비활성 시 휴리스틱 결과만 사용(폴백). FRIDGEMATE_USE_LLM=true 필요.
   |
   v  (2) [목표/미배선] 이 dict -> RAG constraints 로 변환·전달
   |          {cuisine:"한식", max_time:30, nutrient_goal:{protein_min:20},
   |           exclude_ingredients:["계란"]}
   |       * 지금은 이 전달이 없어서 RAG 가 벡터검색만 함(아래 4).
   |
   v  (3) recipe_agent._build_query  ->  query 문자열 (pantry 임박재료 + user_input)
   |
   v  (4) retrieve_recipes -> search(HyDE | RAG-Fusion) -> ChromaDB
   |          벡터 유사도 (constraints 오면 + where 메타필터 동시)
   |          -> to_contract 로 계약 dict 변환
   |
   v  (5) [응답] 계약 dict list  +  부수효과 state["recipe_search_trace"]
   |          recipe_agent 가 results[:3] -> state["selected_recipes"] 에 저장
   |
   v  (6) [다시 에이전트 진행] 그래프가 다음 노드로:
              meal_agent 가 state["selected_recipes"] 소비 -> 식단 구성
              -> shopping -> judge -> ... (RAG 는 여기서 손 뗌)
```

**핵심 2가지 (강조):**
1. **(1) intake 의 LLM dict 파싱** — 자연어를 구조화 dict 로 바꾸는 곳. 큰 모델(Sonnet). 모델/2단계 상세는 `docs/agent/llm-models.md` §2.
2. **(5)->(6) 응답 처리 -> 에이전트 복귀** — RAG 응답은 `state["selected_recipes"]`(상위 3) + `recipe_search_trace`로 그래프에 **되돌아가고**, 이후 노드(meal 등)가 그걸 소비한다. RAG 가 끝이 아니라 **에이전트 그래프의 한 단계**임에 주의.

> 현재 살아있는 경로 = (1) 파싱 · (3)~(6) 검색·응답·복귀. 끊긴 곳 = (2) intake dict -> RAG constraints **전달**. 이걸 이으면 영양/재료/시간 필터가 살아난다.

---

## 1. 현재 계약 (실제 코드 기준)

### 1.1 입력 — 자연어 문자열 하나 (constraints 없음)

진입점: `recipe_agent.retrieve_recipes(query: str, state)` ([recipe_agent.py:25](backend/app/agents/recipe_agent.py#L25))
쿼리 생성: `_build_query(state)` ([recipe_agent.py:51](backend/app/agents/recipe_agent.py#L51)) = 유통기한 임박 pantry 재료명 + `user_input` 결합.

```
state.pantry_items = [{name:"두부", expiry_priority:"high"}, {name:"계란"}]
state.user_input   = "고단백 한식 식단 짜줘"
        |
        v  _build_query
query = "두부 고단백 한식 식단 짜줘"        # RAG로 넘어가는 건 이 문자열 하나뿐
```

### 1.2 검색으로 이어지는 경로

```
query
  -> choose_rag_strategy : 공백제거 길이 < 10 -> "HyDE" / >= 10 -> "RAG-Fusion"  (recipe_agent.py:8)
  -> search_sync -> search() -> hyde_search | rag_fusion_search                  (integration.py:143)
  -> retriever.search_recipes(query, k, cuisine_filter=None, max_time=None)      (retriever.py:27)
  -> col.query(query_embeddings=벡터, where=None)                                 # 필터 안 옴 = 벡터만
  -> to_contract 로 계약 dict 변환                                                (integration.py:75)
```

### 1.3 응답 — 계약 dict 리스트

```jsonc
// retrieve_recipes 반환값 — state["selected_recipes"] 에 상위 3개 저장
[
  {
    "id": "cookrcp-2891",                       // 소스접두-원본ID (dedup 키, 출처 추적)
    "name": "닭가슴살 채소쌈",
    "text": "조리과정 텍스트 join",
    "ingredients": [
      {"name": "닭가슴살", "amount": 120, "unit": "g"},   // qty -> amount (미상은 1로 코어스)
      {"name": "양상추",   "amount": 30,  "unit": "g"}
    ],
    "nutrition": {"calories": 210, "protein": 23.7, "carbs": 8.0, "fat": 5.0},  // carb -> carbs
    "score": 0.87,                              // 0..1 정규화 유사도
    "citation_url": "https://www.foodsafetykorea.go.kr",  // 기관 도메인 (레시피별 deep-link 아님)
    "final_score": 0.87
  }
  // ...
]
```

부수효과: `state["recipe_search_trace"] = {strategy, original_query, n_results, via, top, embedder}`.

소비자(다 충족 중): recipe_agent(name/ingredients/nutrition/score) · meal_agent(name/ingredients.name/nutrition) · shopping_agent(name/ingredients{name,amount,unit}).

---

## 2. 구현 목표 계약 (필터 동시검색)

### 2.1 입력 — query + constraints

```python
retrieve_recipes(
    query = "매콤한 두부 요리",          # 의미검색용 (벡터)
    constraints = {                      # 정확 필터용 (메타 where + 후처리)
        "cuisine": "한식",
        "max_time": 30,
        "nutrient_goal": {"protein_min": 20, "calories_max": 600},
        "include_ingredients": ["두부"],
        "exclude_ingredients": ["계란"],   # 알레르기/제약
    },
    state = ...,
)
```

| constraints 키 | 의미 | 처리 방식 |
|---|---|---|
| `cuisine` | 장르 (한식/양식...) | ChromaDB `where` 직접 |
| `max_time` | 조리시간 상한(분) | ChromaDB `where` ($lte) |
| `nutrient_goal.protein_min` 등 | 영양 하한/상한 | ChromaDB `where` ($gte/$lte) |
| `include_ingredients` | 포함 재료 | **검색 후 후처리**(아래 3-2) |
| `exclude_ingredients` | 제외 재료(알레르기) | **검색 후 후처리** |

### 2.2 검색 경로 (확장)

```
벡터:  "매콤한 두부 요리" 임베딩  (그대로)
where: cuisine_type="한식" AND time_min<=30 AND protein>=20 AND calories<=600   # 숫자/장르 = ChromaDB 직접
후처리: include/exclude_ingredients 로 결과 거름                                  # 재료 = 파이썬 후처리
  -> to_contract
```

### 2.3 응답 — 형태 동일 (변경 없음)

1.3 의 계약 dict 그대로. `trace`에 `applied_filters`(적용된 where + 후처리)만 추가 권장.

---

## 3. constraints 파싱은 누가? — **에이전트가 한다** (결정)

| 기준 | 에이전트가 파싱(구조화 dict 넘김) | RAG가 자연어 받아 직접 추출 |
|---|---|---|
| 관심사 | 의도해석=오케스트레이션 / 검색=RAG (분리) | RAG가 둘 다 (책임 비대) |
| 재사용 | recipe·meal·shopping·v3 가 같은 dict 계약 | 소비자별 해석을 RAG가 떠안음 |
| 테스트 | dict 명시 -> 모킹/단위테스트 쉬움 | RAG 내부 LLM 파싱 -> 비결정 |
| 비용 | intake가 이미 user_input 파싱 -> 같이 뽑으면 LLM 중복 0 | constraints용 LLM 별도 호출 |

**결론**: intake/recipe_agent가 자연어를 파싱해 구조화 `constraints` dict를 만들어 넘긴다. RAG는 그 dict를 받아 **기계적으로 필터만** 한다(자연어에서 직접 추출 안 함). 하위호환: **constraints 없으면 벡터만** 동작(현행 유지). 근거: CLAUDE.md §4-A "스마트 입력 한 줄 -> AI 파싱 -> 폼 자동 채움"이 이미 intake에서 constraints를 파싱하는 설계라 RAG가 중복할 이유가 없다.

---

## 4. 구현 시 반드시 알아야 할 3가지

1. **영양/시간/장르 = ChromaDB `where` 직접 가능** (숫자/문자 메타). 데이터는 식약처 1,146건 완비.
2. **재료 포함/제외 = `where`로 직접 안 됨** — `ingredients`가 JSON 문자열로 저장돼 ChromaDB가 내부를 못 본다. **검색 후 파이썬 후처리**로 거른다. (필터로 n이 줄 수 있으니 검색 k를 넉넉히 뽑고 후처리)
3. **농정원 537건은 영양 0** — `protein_min` 필터에 자동 탈락. "거짓 통과"는 안 생기나 **"데이터 없음"과 "진짜 0"을 구분 못 해 농정원이 영양 필터에선 통째로 빠진다.** 의도된 동작인지 합의 필요(안전 측면에선 빠지는 게 맞음).

---

## 5. 작업 + 소유 (R&R)

| # | 작업 | 소유 |
|---|---|---|
| 1 | `retriever.search_recipes` where에 protein/calories 추가 + 재료 후처리 | **RAG 단독** |
| 2 | `integration.search` constraints 파싱 확장 + `retrieve_recipes` 시그니처에 constraints 추가 | **RAG 단독** |
| 3 | recipe_agent가 user_input에서 constraints 뽑아 넘기는 배선 | **에이전트 파트 협의** |
| 4 | `FridgeMateState`에 constraints 필드 추가 여부 | **팀 계약 협의** |

1,2(RAG 단독)는 식약처 데이터로 바로 동작 검증 가능. 3,4는 에이전트/state 계약이라 협의 필요.

---

## 6. 합의 필요 (팀)

- `FridgeMateState`에 `constraints` 필드 추가 (또는 기존 필드 재사용) — 에이전트->RAG 전달 통로.
- 영양 필터에서 농정원(영양 0)을 빼는 게 맞는지 (데이터 없음 vs 진짜 0).
- 관련 문서: [rag-support-plan.md](rag-support-plan.md)(보강 작업 전반), [rag-INDEX.md](rag-INDEX.md)(문서 인덱스).
