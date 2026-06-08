# FridgeMate 에이전트 파이프라인 전체 흐름

> 작성일: 2026-06-08  
> 담당: 전영주  
> 관련 파일: `pantry_agent.py`, `recipe_agent.py`, `meal_agent.py`, `shopping_agent.py`

---

## 1. 전체 파이프라인 구조

```
[사용자 입력]
     │
     ▼
[프론트엔드 chatAdapter.ts]
  - excludedIngredients를 ingredients에서 제거
  - 구조화 입력 → 자연어 message 생성
  - excluded_ingredients 별도 필드로 전달
     │
     ▼ POST /chat (ChatRequest)
[main.py]
  - ChatRequest 수신
  - nutrition_goal dict 조립
  - excluded_ingredients state에 저장
  - graph.invoke() 호출
     │
     ▼
┌────────────────────────────────────────────────────┐
│               LangGraph orchestrator               │
│                                                    │
│  [1] pantry_agent                                  │
│       ↓ pantry_items, pantry_analysis              │
│  [2] recipe_agent                                  │
│       ↓ selected_recipes, recipe_search_trace      │
│  [3] meal_agent                                    │
│       ↓ meal_plan, nutrition_result                │
│  [4] shopping_agent                                │
│       ↓ missing_ingredients                        │
│  [5] executor_agent (Coupang 팀)                   │
│       ↓ cart_items                                 │
└────────────────────────────────────────────────────┘
     │
     ▼
[최종 응답 반환]
```

---

## 2. 프론트엔드 → 백엔드 입력 계약

### `chatAdapter.ts` → `main.py`

```
사용자 UI 입력값:
  ingredients         = "닭가슴살, 계란, 브로콜리, 두부"
  excludedIngredients = "닭가슴살"
  goal                = "고단백 저탄수"
  peopleCount         = 2
  maxCookingMinutes   = 20
  calorieTargetKcal   = 1700
  proteinTargetGram   = 120
  deliveryPreference  = "freshness"
  mode                = "goal"
        ↓ mapRequestToChat()
  ① excludedSet = {"닭가슴살"}
  ② filteredIngredients = "계란, 브로콜리, 두부"  ← 닭가슴살 제거
  ③ message = "냉장고에 계란, 브로콜리, 두부 있어. 고단백 저탄수. 2인분, 조리 20분 이내,
               칼로리 1700kcal, 단백질 120g, 닭가슴살 제외, 배송 freshness, goal 모드. 식단 짜줘"
        ↓ POST /chat
ChatRequest {
  message:              "냉장고에 계란, 브로콜리, 두부 있어. ..."
  excluded_ingredients: "닭가슴살"          ← 별도 필드
  protein_target_gram:  120
  calorie_target_kcal:  1700
  ingredient_entries:   [{ name, amount, expiration_date, storage_type }, ...]
  budget_limit:         null
}
```

### `main.py` → `graph.invoke()`

```python
graph.invoke({
    "user_input":            "냉장고에 계란, 브로콜리, 두부 있어. ...",
    "ingredient_entries":    [{ name, amount, expiration_date, storage_type }],
    "excluded_ingredients":  "닭가슴살",
    "nutrition_goal": {
        "protein_target":  120,
        "calorie_target":  1700,
    },
    "budget_limit":  None,
    "retry_count":   0,
    "logs":          [],
})
```

---

## 3. AGENT 1: `pantry_agent`

### 역할
`ingredient_entries`를 파싱해 유통기한 우선순위를 계산하고  
후속 에이전트가 사용하는 `pantry_items`와 UI용 `pantry_analysis`를 생성한다.

### 입력 (state)

```python
{
    "ingredient_entries": [
        {"name": "닭가슴살", "amount": "500g",  "expiration_date": "2026-06-10", "storage_type": "냉장 보관"},
        {"name": "계란",     "amount": "10개",  "expiration_date": "2026-06-08", "storage_type": "냉장 보관"},
        {"name": "브로콜리", "amount": "300g",  "expiration_date": "2026-06-09", "storage_type": "냉장 보관"},
        {"name": "두부",     "amount": "1모",   "expiration_date": "2026-06-07", "storage_type": "냉장 보관"},
    ]
}
```

### 처리 흐름

```
ingredient_entries
      ↓
① parse_amount_unit()
   "500g" → (500.0, "g")
   "10개" → (10.0,  "개")
   "1모"  → (1.0,   "모")
      ↓
② calculate_days_left()
   "2026-06-10" → D+2  (오늘: 2026-06-08 기준)
   "2026-06-08" → D+0  ← 오늘 만료 ⚠️
   "2026-06-09" → D+1
   "2026-06-07" → D-1  ← 이미 만료 ⚠️
      ↓
③ expiry_priority + freshness 계산
   D-1 이하  → high   / urgent
   D 0~3일   → high   / urgent
   D 4~7일   → normal / soon
   D 8일 이상 → normal / fresh
      ↓
④ build_pantry_items()     → recipe_agent / shopping_agent 용
   build_pantry_analysis() → UI PantryCard 용
```

### 출력 (state에 추가)

```python
# ① pantry_items → recipe_agent, shopping_agent 가 사용
"pantry_items": [
    {"name": "닭가슴살", "amount": 500.0, "unit": "g",  "expiry_priority": "normal", "expiration_date": "2026-06-10"},
    {"name": "계란",     "amount": 10.0,  "unit": "개", "expiry_priority": "high",   "expiration_date": "2026-06-08"},  # ⚠️
    {"name": "브로콜리", "amount": 300.0, "unit": "g",  "expiry_priority": "high",   "expiration_date": "2026-06-09"},  # ⚠️
    {"name": "두부",     "amount": 1.0,   "unit": "모", "expiry_priority": "high",   "expiration_date": "2026-06-07"},  # ⚠️
]

# ② pantry_analysis → UI PantryCard 가 사용
"pantry_analysis": {
    "items": [
        {"name": "닭가슴살", "freshness": "soon",   "expiry_label": "2일 남음"},
        {"name": "계란",     "freshness": "urgent", "expiry_label": "오늘 만료"},
        {"name": "브로콜리", "freshness": "urgent", "expiry_label": "1일 남음"},
        {"name": "두부",     "freshness": "urgent", "expiry_label": "만료됨"},
    ],
    "priority_use": ["계란", "브로콜리", "두부"],
    "summary": "유통기한이 가까운 계란, 브로콜리, 두부을(를) 우선 사용하는 식단을 구성할게요."
}
```

---

## 4. AGENT 2: `recipe_agent`

### 역할
`pantry_items`와 `excluded_ingredients`를 기반으로 RAG 검색 쿼리를 생성하고  
ChromaDB에서 레시피를 검색한 뒤 제외 재료 필터링 후 상위 9개를 반환한다.

### 입력 (state — pantry_agent 결과 포함)

```python
{
    "pantry_items":           [닭가슴살(normal), 계란(high), 브로콜리(high), 두부(high)],
    "excluded_ingredients":   "닭가슴살",
    "user_input":             "냉장고에 계란, 브로콜리, 두부 있어. ...",
}
```

### 처리 흐름

```
① _build_query(state)
   excluded_names    = {"닭가슴살"}
   filtered_pantry   = [계란, 브로콜리, 두부]       ← 닭가슴살 제거
   priority_names    = ["계란", "브로콜리", "두부"]  ← high 재료
   query = "계란 브로콜리 두부 냉장고에 계란, 브로콜리, 두부 있어. ..."
      ↓
② choose_rag_strategy(query)
   공백제거 길이 >= 10 → RAG-Fusion 선택
      ↓
③ retrieve_recipes(query, state)
   rag_fusion_search() 호출
     - 4가지 관점 쿼리 생성 (원본 / 레시피 / 추천 / 요리)
     - 각각 ChromaDB 검색 (k_fetch = max(k×3, 20))
     - RRF 점수 병합 → 상위 10개
   → to_contract() 변환 (carb→carbs, qty→amount)
      ↓
④ _filter_excluded(results, "닭가슴살")
   검사 1: ingredients 필드 정확한 이름 매칭
   검사 2: 레시피 이름 부분 포함 검사
   예) "닭가슴살 두부선"  → name에 "닭가슴살" 포함 → 제외
       "구운 닭고기 샐러드" → ingredients에 "닭가슴살" 포함 → 제외
       "두부오믈렛"       → 해당 없음 → 유지 ✅
   필터 후 0개 → fallback(원본 반환)
      ↓
⑤ filtered[:9] → 상위 9개 선택
```

### 출력 (state에 추가)

```python
# selected_recipes → meal_agent, shopping_agent 가 사용
"selected_recipes": [
    {
        "id": "rcp_1", "name": "두부오믈렛",
        "ingredients": [{"name": "두부", "amount": 200, "unit": "g"}, ...],
        "nutrition": {"calories": 280, "protein": 22, "carbs": 12, "fat": 18},
        "citation_url": "https://...",
    },
    # ... 총 9개
]

# recipe_search_trace → UI 표시용
"recipe_search_trace": {
    "strategy": "RAG-Fusion",
    "original_query": "계란 브로콜리 두부 냉장고에...",
    "n_results": 9,
    "excluded": "닭가슴살",
}
```

---

## 5. AGENT 3: `meal_agent`

### 역할
`selected_recipes`(9개)를 LLM에 전달해 3일×3끼 식단을 생성하고  
영양 목표 달성 여부를 하루 평균 기준으로 검증한다.

### 입력 (state — recipe_agent 결과 포함)

```python
{
    "pantry_items":      [닭가슴살, 계란, 브로콜리, 두부],
    "selected_recipes":  [9개 레시피],
    "nutrition_goal": {
        "protein_target":  120,
        "calorie_target":  1700,
    },
    "user_input": "냉장고에 계란, 브로콜리, 두부 있어. ...",
}
```

### 처리 흐름

```
STEP 1. create_weekly_plan()
      ↓
  ① _sort_recipes_by_slot()
     9개 칼로리 오름차순 정렬 후 3등분
       하위 3개 → morning_titles (아침: 저칼로리)
       중간 3개 → dinner_titles  (저녁: 중칼로리)
       상위 3개 → lunch_titles   (점심: 고칼로리)
      ↓
  ② LLM 1회 호출 (슬롯별 추천 목록 포함)
     [system_prompt] 슬롯 배치 규칙 포함
     [user_prompt]
       - 사용자 요청
       - 냉장고 재료 목록
       - 임박 재료: [계란, 브로콜리, 두부]
       - 허용 레시피 목록 (9개)
       - 아침 추천: [두부오믈렛, 브로콜리 두부 샐러드, 두부곤약조림]
       - 점심 추천: [닭가슴살 두부 스테이크, ...]
       - 저녁 추천: [두부 된장찌개, ...]
     → meal_plan JSON 생성
      ↓
  ③ _ensure_unique_recipes()
     허용 목록 벗어난 recipeTitle → 미사용 레시피로 교체
     중복 recipeTitle             → 미사용 레시피로 교체
      ↓
  ④ _mark_priority_items()
     recipeTitle에 [계란, 브로콜리, 두부] 포함 → usesPriorityItem=True
      ↓
  ⑤ _apply_slot_calories()   ← swap 방식
     아침 슬롯에 lunch_titles 레시피 있으면
       → 다른 슬롯의 morning_titles 레시피와 서로 swap
     usesPriorityItem=True 이면 swap 건너뜀

STEP 2. verify_nutrition_goal()
  ① 9개 레시피 영양 전체 합산
     calories: 3,200 / protein: 267 / carbs: 190 / fat: 126
  ② ÷ num_days(3) → 하루 평균
     calories: 1,067 / protein: 89 / carbs: 63 / fat: 42
  ③ 하루 목표와 비교
     protein  89 >= 120  → False ❌
     calories 1067 >= 1530 → False ❌
     → passed = False
  ④ _build_warnings() / _build_message() → 한국어 경고 생성

LLM 실패 시 fallback:
  selected_recipes[0~8] 순서대로 자동 배치
  1일차: [0]아침 [1]점심 [2]저녁
  2일차: [3]아침 [4]점심 [5]저녁
  3일차: [6]아침 [7]점심 [8]저녁
```

### 출력 (state에 추가)

```python
# meal_plan → UI MealPlanCard 가 사용
"meal_plan": {
    "note": "임박 재료를 앞쪽 일자에 배치했어요.",
    "days": [
        {"label": "1일차", "entries": [
            {"slot": "아침", "recipeTitle": "두부오믈렛",            "usesPriorityItem": True},
            {"slot": "점심", "recipeTitle": "닭가슴살 두부 스테이크", "usesPriorityItem": True},
            {"slot": "저녁", "recipeTitle": "두부 된장찌개",          "usesPriorityItem": True},
        ]},
        # ... 2일차, 3일차
    ]
}

# nutrition_result → UI NutritionCard 가 사용
"nutrition_result": {
    "protein":  {"current": 89,   "target": 120,  "unit": "g"},
    "calories": {"current": 1067, "target": 1700, "unit": "kcal"},
    "carbs":    {"current": 63,   "target": 150,  "unit": "g"},
    "fat":      {"current": 42,   "target": 55,   "unit": "g"},
    "passed":   False,
    "message":  "목표 영양소를 충족하지 못했어요.",
    "warnings": ["단백질이 목표(120g)에 미달해요.", "칼로리가 목표(1700kcal) 대비 부족해요."],
}

# selected_recipes → shopping_agent 로 그대로 전달 (오염 없음)
```

---

## 6. AGENT 4: `shopping_agent`

### 역할
`meal_plan`에서 실제 사용된 레시피를 추출하고 `pantry_items`와 비교해  
실제 구매가 필요한 부족 재료 목록을 계산한다. **(LLM/RAG 없음, 순수 계산)**

### 입력 (state — meal_agent 결과 포함)

```python
{
    "meal_plan":        {3일 × 3끼 식단},
    "selected_recipes": [9개 레시피 + 재료 목록],
    "pantry_items":     [닭가슴살, 계란, 브로콜리, 두부],
}
```

### 처리 흐름

```
STEP A. _collect_used_recipes()
  meal_plan.days[].entries[].recipeTitle 순회
  → recipeTitle 사용 횟수 집계 (title_counts)
  → selected_recipes에서 재료 목록 매핑
  ⚠️ selected_recipes에 없는 recipeTitle → ingredients=[] + warning

  예시:
  title_counts = {
    "두부오믈렛":             1,
    "닭가슴살 두부 스테이크":  2,
    "두부 된장찌개":           1,
    ...
  }
      ↓
STEP B. _aggregate_ingredients()
  재료명 기준 합산 + 사용 횟수(count) 배수 적용
  _normalize_name()  → 재료명 띄어쓰기 정규화
  _parse_amount()    → "12g+3" → 12.0 (안전 파싱)
  _normalize_unit()  → "g+3"  → "g"  (정규화)

  예시:
  닭가슴살 두부 스테이크 (count=2):
    두부     100g × 2 = 200g
    파프리카 100g × 2 = 200g
    허브     None × 2 = None  ← amount=None 유지
      ↓
STEP C. _calc_missing()
  pantry_names = {닭가슴살, 계란, 브로콜리, 두부}
  aggregated 재료 중 pantry에 없는 것만 필터
  → 이름 오름차순 정렬
  ⚠️ 양 비교 없음 — 이름만 비교 (pantry amount 신뢰도 낮음)
```

### 엣지케이스 처리

| 상황 | 처리 방식 |
|------|-----------|
| 같은 재료, 다른 단위 | `"재료\|\|g"` vs `"재료\|\|개"` 별도 키 → Coupang 팀 판단 |
| `amount=None` | `None` 유지 → Coupang 팀 기본 수량으로 검색 |
| `unit=""` | `None`으로 정규화 |
| 재료명 띄어쓰기 불일치 | `_normalize_name()` 으로 정규화 |

### 출력 (state에 추가)

```python
# missing_ingredients → Coupang 팀 → cart_items 생성
"missing_ingredients": [
    {"name": "된장",       "amount": 60,   "unit": "g",  "needed_by": ["닭가슴살 두부 강된장 덮밥"]},
    {"name": "소금",       "amount": 4,    "unit": "g",  "needed_by": ["브로콜리 계란 스크램블"]},
    {"name": "양파",       "amount": 200,  "unit": "g",  "needed_by": ["닭가슴살 두부 강된장 덮밥"]},
    {"name": "올리브오일", "amount": 20,   "unit": "ml", "needed_by": ["브로콜리 계란 스크램블"]},
    {"name": "파프리카",   "amount": 200,  "unit": "g",  "needed_by": ["닭가슴살 두부 스테이크"]},
    {"name": "허브",       "amount": None, "unit": None, "needed_by": ["닭가슴살 두부 스테이크"]},
    {"name": "현미밥",     "amount": 400,  "unit": "g",  "needed_by": ["닭가슴살 두부 강된장 덮밥"]},
]
```

---

## 7. AGENT 간 상호작용 데이터 흐름

```
┌──────────────────────────────────────────────────────────────────────┐
│                        FridgeMateState                               │
│                                                                      │
│  [pantry_agent 출력]                                                 │
│   pantry_items     ──────────────────────┬──────────────────────┐   │
│   pantry_analysis  → UI PantryCard       │                      │   │
│                                          │                      │   │
│  [recipe_agent 출력]                     ↓                      ↓   │
│   selected_recipes  ──────────────┬─ meal_agent            shopping │
│   recipe_search_trace → UI 표시   │    (레시피 9개 사용)      _agent │
│                                   │                         (재료   │
│  [meal_agent 출력]                ↓                          비교)  │
│   meal_plan        → UI MealPlanCard                         ↑      │
│   nutrition_result → UI NutritionCard                        │      │
│   selected_recipes ──────────────────────────────────────────┘      │
│   (오염 없이 그대로 전달)                                             │
│                                                                      │
│  [shopping_agent 출력]                                               │
│   missing_ingredients → Coupang 팀 → cart_items                     │
│                                                                      │
└──────────────────────────────────────────────────────────────────────┘
```

---

## 8. 핵심 설계 원칙

### 원칙 1: selected_recipes 불변성
```
recipe_agent   → selected_recipes 생성 (9개)
meal_agent     → selected_recipes 읽기만 (수정 ❌)
shopping_agent → selected_recipes 읽기만 (수정 ❌)

이유: meal_agent가 selected_recipes를 오염시키면
     shopping_agent의 재료 집계가 틀어짐
```

### 원칙 2: excluded_ingredients 2중 필터
```
① chatAdapter.ts
   ingredients에서 excluded 재료 제거
   → message에 닭가슴살 포함 안 됨
   → RAG 쿼리에 닭가슴살 없음 → 닭가슴살 레시피 검색 안 됨

② recipe_agent._filter_excluded()
   RAG 결과에서 닭가슴살 레시피 완전 제거
   → ingredients 이름 매칭 + 레시피 이름 부분 검사
```

### 원칙 3: 영양 계산 하루 평균 기준
```
9개 레시피 합산 ÷ 3(num_days) = 하루 평균
하루 평균 vs 하루 목표값 비교

이유: 목표값(1700kcal)은 하루 기준
     9개 합산(4500kcal)과 비교하면 항상 초과로 판정
```

### 원칙 4: LLM 최소 호출
```
pantry_agent   → LLM 없음 (순수 계산)
recipe_agent   → LLM 없음 (RAG 검색만)
meal_agent     → LLM 1회 (식단 생성만)
shopping_agent → LLM 없음 (순수 계산)
```

---

## 9. 에러 처리 및 Fallback

| 에이전트 | 에러 케이스 | Fallback |
|----------|------------|---------|
| `pantry_agent` | `ingredient_entries` 없음 | `pantry_items=[]` 반환 |
| `recipe_agent` | `pantry_items` 없음 | `selected_recipes=[]` 조기 반환 |
| `recipe_agent` | ChromaDB 연결 실패 | `selected_recipes=[]` + 에러 로그 |
| `recipe_agent` | `_filter_excluded` 후 0개 | 필터 미적용 → 원본 반환 |
| `meal_agent` | LLM 호출 실패 | `selected_recipes[0~8]` 순서 자동 배치 |
| `meal_agent` | JSON 파싱 오류 | 동일 fallback |
| `shopping_agent` | `meal_plan` 없음 | `missing_ingredients=[]` 반환 |
| `shopping_agent` | recipeTitle 매핑 실패 | `ingredients=[]` + warning 로그 |

---

## 10. 전체 state 키 요약

```python
FridgeMateState = {
    # ── 입력 ────────────────────────────────────
    "user_input":            str,           # chatAdapter.ts 생성 자연어
    "ingredient_entries":    list[dict],    # 프론트 구조화 입력
    "excluded_ingredients":  str,           # "닭가슴살,돼지고기" 형식
    "nutrition_goal":        dict,          # 하루 기준 목표값
    "budget_limit":          int | None,

    # ── pantry_agent 출력 ────────────────────────
    "pantry_items":          list[dict],    # recipe/shopping agent 용
    "pantry_analysis":       dict,          # UI PantryCard 용

    # ── recipe_agent 출력 ────────────────────────
    "selected_recipes":      list[dict],    # 상위 9개 레시피
    "recipe_search_trace":   dict,          # 검색 전략/결과 메타

    # ── meal_agent 출력 ──────────────────────────
    "meal_plan":             dict,          # 3일 × 3끼 식단
    "nutrition_result":      dict,          # 하루 평균 영양 검증

    # ── shopping_agent 출력 ──────────────────────
    "missing_ingredients":   list[dict],    # 부족 재료 목록
    "cart_items":            list[dict],    # Coupang 팀 완성

    # ── 공통 ────────────────────────────────────
    "logs":                  list[dict],    # 파이프라인 전체 로그
    "route":                 str,           # 라우팅 정보
    "retry_count":           int,
    "final_response":        str,
}
```

---

## 11. 테스트 실행 순서 (서버 필요 여부)

| 순서 | 테스트 파일 | LM Studio | ChromaDB | 비고 |
|------|------------|-----------|----------|------|
| 1 | `test_pantry_agent.py` | ❌ | ❌ | 서버 불필요 |
| 2 | `test_shopping_agent.py` | ❌ | ❌ | 서버 불필요 |
| 3 | `test_meal_agent.py` (STEP 1~6) | ❌ | ❌ | 순수 계산 함수만 |
| 4 | `test_recipe_agent.py` (STEP 1~6) | ❌ | ✅ 필요 | RAG 검색 |
| 5 | `test_meal_agent.py` (STEP 7~10) | ✅ 필요 | ❌ | LLM 호출 |
| 6 | `test_recipe_agent.py` (STEP 7~13) | ✅ 필요 | ✅ 필요 | 전체 |

```powershell
cd D:\07.Coding\ku_agent\FridgeMate\backend

# 서버 불필요 테스트 먼저
python tests/test_pantry_agent.py
python tests/test_shopping_agent.py

# ChromaDB 필요
python