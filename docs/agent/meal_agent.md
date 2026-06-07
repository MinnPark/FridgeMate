# meal_agent.py 개발 문서

> 작성일: 2026-06-06  
> 최종 수정: 2026-06-07  
> 담당: 전영주  
> 관련 파일: `app/agents/meal_agent.py`, `app/tools/nutrition_tools.py`, `app/prompts/meal_prompts.py`, `app/main.py`

---

## 개요

`meal_agent`는 FridgeMate 파이프라인의 **3번째 에이전트**다.  
`recipe_agent`가 검색한 레시피를 바탕으로 **3일 meal prep 식단 계획을 생성**하고  
**영양 목표 달성 여부를 검증**한다.

```
pantry_agent (1) → recipe_agent (2) → meal_agent (3) → shopping_agent (4) → executor_agent (5)
```

---

## 입력 / 출력

### 입력 (`FridgeMateState`)

| 키 | 출처 | 설명 |
|----|------|------|
| `pantry_items` | `pantry_agent` | 재료 목록 + `expiry_priority` |
| `selected_recipes` | `recipe_agent` | RAG 검색된 레시피 상위 3개 |
| `nutrition_goal` | `main.py ChatRequest` | 단백질·칼로리·탄수화물·지방 목표값 (모두 optional) |
| `user_input` | 사용자 입력 | 자연어 요청 |

> `nutrition_goal`은 `main.py`의 `ChatRequest`에서 아래 4개 필드로 받아 dict로 조립된다.
> ```python
> # main.py ChatRequest 필드
> protein_target_gram:  int | None  # → nutrition_goal["protein_target"]
> calorie_target_kcal:  int | None  # → nutrition_goal["calorie_target"]
> carbs_target_gram:    int | None  # → nutrition_goal["carbs_target"]
> fat_target_gram:      int | None  # → nutrition_goal["fat_target"]
> # 모두 None이면 빈 dict → nutrition_tools.py 기본값 사용
> ```

### 출력 (`FridgeMateState`)

| 키 | 사용처 | 설명 |
|----|--------|------|
| `meal_plan` | UI `MealPlanCard` | 3일 × 3끼 식단 계획 |
| `nutrition_result` | UI `NutritionCard` | 영양 합산 + 목표 검증 결과 |
| `selected_recipes` | `shopping_agent` | **recipe_agent 결과 그대로 유지 (오염 없음)** |
| `logs` | UI `AgentPipelinePanel` | 실행 이벤트 로그 |

---

## 전체 실행 흐름

```
meal_agent(state)
    │
    ├── 1. create_weekly_plan(state)     ← LLM 1회 호출
    │       └── _mark_priority_items()  ← usesPriorityItem 자동 보정 (LLM 없음)
    │
    ├── 2. verify_nutrition_goal()       ← 영양 합산 계산 (LLM 없음, RAG 없음)
    │       ├── _build_warnings()        ← 한국어 경고 문장 생성
    │       └── _build_message()         ← 한국어 요약 메시지 생성
    │
    └── 3. return state
            ├── meal_plan
            ├── nutrition_result
            ├── selected_recipes  ← recipe_agent 결과 그대로 (변경 없음)
            └── logs
```

> ⚠️ **`execute_meal_plan()` 제거됨 (2026-06-07)**  
> 기존에는 3일 × 3끼마다 RAG-Fusion을 실행해 레시피를 추가 수집했으나  
> 아래 두 가지 문제로 완전 제거됨:  
> 1. **RAG 9회 과도 호출** — 요청 1회당 최대 9번 ChromaDB 검색  
> 2. **영양 계산 오염** — 검색 결과 수십 개를 `selected_recipes`에 추가해  
>    실제 식단 섭취량이 아닌 검색 결과 전체 합산으로 수치가 크게 부풀었음

---

## 테스트 시나리오 (오늘: 2026-06-06)

### 입력 데이터

```python
# 냉장고 재료
TEST_PANTRY_ITEMS = [
    {"name": "닭가슴살", "expiry_priority": "normal", "expiration_date": "2026-06-10"},  # D+4
    {"name": "계란",     "expiry_priority": "high",   "expiration_date": "2026-06-07"},  # D+1
    {"name": "브로콜리", "expiry_priority": "high",   "expiration_date": "2026-06-08"},  # D+2
    {"name": "두부",     "expiry_priority": "high",   "expiration_date": "2026-06-06"},  # D+0 ⚠️
]

# recipe_agent가 검색한 레시피
TEST_SELECTED_RECIPES = [
    {
        "id": "rcp_1",
        "name": "닭가슴살 두부 강된장 덮밥",
        "nutrition": {"calories": 520, "protein": 45, "carbs": 38, "fat": 14},
    },
    {
        "id": "rcp_2",
        "name": "브로콜리 계란 스크램블",
        "nutrition": {"calories": 280, "protein": 22, "carbs": 12, "fat": 18},
    },
    {
        "id": "rcp_3",
        "name": "닭가슴살 두부 스테이크",
        "nutrition": {"calories": 410, "protein": 48, "carbs": 8, "fat": 16},
    },
]

# 영양 목표 (main.py ChatRequest → graph.invoke() 에서 dict로 조립)
TEST_NUTRITION_GOAL = {
    "protein_target":  120,   # g
    "calorie_target":  1700,  # kcal
    "carbs_target":    150,   # g
    "fat_target":      55,    # g
}
```

---

## STEP 1: `create_weekly_plan()` — LLM 식단 생성

### 역할

`selected_recipes`와 `pantry_items`를 LLM에 전달해  
**3일 × 3끼 식단 계획 JSON**을 생성한다. **(LLM 1회만 호출)**

### LLM에 전달하는 user_prompt

```
사용자 요청: 냉장고에 닭가슴살, 계란, 브로콜리, 두부 있어. 고단백 저탄수. 2인분...
냉장고 재료: ['닭가슴살', '계란', '브로콜리', '두부']
유통기한 임박 재료(priority_items): ['계란', '브로콜리', '두부']   ← expiry_priority == "high"
선택된 레시피 목록(반드시 이 목록에서만 선택): ['닭가슴살 두부 강된장 덮밥', '브로콜리 계란 스크램블', '닭가슴살 두부 스테이크']
영양 목표: {'protein_target': 120, 'calorie_target': 1700, ...}
```

### LLM 출력 (정상)

```json
{
  "note": "임박 재료를 앞쪽 일자에 배치했어요.",
  "days": [
    {
      "label": "1일차",
      "entries": [
        {"slot": "아침", "recipeTitle": "브로콜리 계란 스크램블",    "usesPriorityItem": true},
        {"slot": "점심", "recipeTitle": "닭가슴살 두부 강된장 덮밥", "usesPriorityItem": true},
        {"slot": "저녁", "recipeTitle": "닭가슴살 두부 스테이크",    "usesPriorityItem": true}
      ]
    },
    {
      "label": "2일차",
      "entries": [
        {"slot": "아침", "recipeTitle": "그릭요거트 + 방울토마토"},
        {"slot": "점심", "recipeTitle": "닭가슴살 두부 강된장 덮밥"},
        {"slot": "저녁", "recipeTitle": "브로콜리 계란 스크램블"}
      ]
    },
    {
      "label": "3일차",
      "entries": [
        {"slot": "아침", "recipeTitle": "계란 현미 주먹밥"},
        {"slot": "점심", "recipeTitle": "닭가슴살 두부 스테이크"},
        {"slot": "저녁", "recipeTitle": "닭가슴살 채소 볶음"}
      ]
    }
  ]
}
```

### LLM 실패 시 fallback

LLM 호출이 실패하거나 JSON 파싱 오류 발생 시 `selected_recipes` 기반으로 자동 생성한다.

```python
fallback = {
    "note": "임박 재료를 앞쪽 일자에 배치했어요.",
    "days": [
        {
            "label": "1일차",
            "entries": [
                {"slot": "아침",  "recipeTitle": "브로콜리 계란 스크램블",    "usesPriorityItem": True},
                {"slot": "점심",  "recipeTitle": "닭가슴살 두부 강된장 덮밥", "usesPriorityItem": True},
                {"slot": "저녁",  "recipeTitle": "닭가슴살 두부 스테이크",    "usesPriorityItem": True},
            ],
        },
        ...
    ],
}
```

---

## STEP 1-1: `_mark_priority_items()` — usesPriorityItem 자동 보정

### 역할

LLM이 `usesPriorityItem`을 **누락하거나 잘못 표시한 경우** 자동으로 보정한다.  
`recipeTitle`에 `expiry_priority == "high"` 재료 이름이 포함되어 있으면 `true`로 설정한다.

### 보정 규칙

```
priority_names = ["계란", "브로콜리", "두부"]   ← expiry_priority == "high"

recipeTitle에 priority_names 중 하나라도 포함  →  usesPriorityItem = True
recipeTitle에 priority_names 없음              →  usesPriorityItem = False
```

### 보정 전 / 후 비교

| 일차 | 슬롯 | recipeTitle | 보정 전 | 보정 후 | 이유 |
|------|------|-------------|---------|---------|------|
| 1일차 | 아침 | 브로콜리 계란 스크램블 | 없음 | `true` ✅ | "브로콜리", "계란" 포함 |
| 1일차 | 점심 | 닭가슴살 두부 강된장 덮밥 | 없음 | `true` ✅ | "두부" 포함 |
| 1일차 | 저녁 | 닭가슴살 채소 볶음 | 없음 | `false` | priority 재료 없음 |
| 2일차 | 아침 | 그릭요거트 + 방울토마토 | 없음 | `false` | priority 재료 없음 |
| 2일차 | 점심 | 두부 된장찌개 | `false` ← LLM 오류 | `true` ✅ | "두부" 포함 → 보정 |
| 2일차 | 저녁 | 계란볶음밥 | 없음 | `true` ✅ | "계란" 포함 |

---

## STEP 2: `verify_nutrition_goal()` — 영양 합산 검증

### 역할

`recipe_agent`의 `selected_recipes` (대표 레시피 3~5개)의 `nutrition` 값을 합산해  
목표 달성 여부를 검증한다.  
**외부 API 불필요** — ChromaDB `recipe_db`에 영양 데이터가 이미 포함되어 있다.  
**RAG 추가 검색 없음** — `execute_meal_plan()` 제거로 `selected_recipes` 오염 없음.

### 합산 계산 (recipe_agent 선택 레시피 3개 기준)

```
레시피                       calories  protein  carbs  fat
─────────────────────────────────────────────────────────
닭가슴살 두부 강된장 덮밥      520       45       38     14
브로콜리 계란 스크램블         280       22       12     18
닭가슴살 두부 스테이크         410       48        8     16
─────────────────────────────────────────────────────────
합계 (totals)               1,210      115       58     48

목표 (targets)              1,700      120      150     55
```

### `passed` 판정 기준

```python
passed = (
    totals["protein"]  >= targets["protein"]             # 115 >= 120  → False ❌
    and totals["calories"] >= targets["calories"] * 0.9  # 1210 >= 1530 → False ❌
    and totals["calories"] <= targets["calories"] * 1.1  # 1210 <= 1870 → True  ✅
)
# → passed = False
```

### `warnings` 생성

```python
warnings = [
    "단백질이 목표(120g)에 미달해요. 닭가슴살·두부를 추가하면 좋아요.",
    # fat(48) < 55 * 0.8(44) → False (경고 없음)
    # carbs(58) > 150 * 1.2(180) → False (경고 없음)
    "칼로리가 목표(1700kcal) 대비 부족해요. 한 끼 분량을 늘려보세요.",
]
```

### 최종 반환값 (`nutrition_result`)

```python
{
    "protein":  {"current": 115,  "target": 120,  "unit": "g"},
    "calories": {"current": 1210, "target": 1700, "unit": "kcal"},
    "carbs":    {"current": 58,   "target": 150,  "unit": "g"},
    "fat":      {"current": 48,   "target": 55,   "unit": "g"},
    "passed":   False,
    "message":  "목표 영양소를 충족하지 못했어요. 아래 경고를 확인해 주세요.",
    "warnings": [
        "단백질이 목표(120g)에 미달해요. 닭가슴살·두부를 추가하면 좋아요.",
        "칼로리가 목표(1700kcal) 대비 부족해요. 한 끼 분량을 늘려보세요.",
    ],
}
```

---

## STEP 3: `meal_agent()` 최종 반환 state

```python
{
    # 기존 state 유지
    **state,

    # meal_agent 출력
    "meal_plan": {
        "note": "임박 재료를 앞쪽 일자에 배치했어요.",
        "days": [
            {
                "label": "1일차",
                "entries": [
                    {"slot": "아침", "recipeTitle": "브로콜리 계란 스크램블",    "usesPriorityItem": True},
                    {"slot": "점심", "recipeTitle": "닭가슴살 두부 강된장 덮밥", "usesPriorityItem": True},
                    {"slot": "저녁", "recipeTitle": "닭가슴살 두부 스테이크",    "usesPriorityItem": True},
                ],
            },
            {
                "label": "2일차",
                "entries": [
                    {"slot": "아침", "recipeTitle": "그릭요거트 + 방울토마토",   "usesPriorityItem": False},
                    {"slot": "점심", "recipeTitle": "닭가슴살 두부 강된장 덮밥", "usesPriorityItem": True},
                    {"slot": "저녁", "recipeTitle": "브로콜리 계란 스크램블",    "usesPriorityItem": True},
                ],
            },
            {
                "label": "3일차",
                "entries": [
                    {"slot": "아침", "recipeTitle": "계란 현미 주먹밥",       "usesPriorityItem": True},
                    {"slot": "점심", "recipeTitle": "닭가슴살 두부 스테이크",  "usesPriorityItem": True},
                    {"slot": "저녁", "recipeTitle": "닭가슴살 채소 볶음",     "usesPriorityItem": False},
                ],
            },
        ],
    },

    "nutrition_result": {
        "protein":  {"current": 115,  "target": 120,  "unit": "g"},
        "calories": {"current": 1210, "target": 1700, "unit": "kcal"},
        "carbs":    {"current": 58,   "target": 150,  "unit": "g"},
        "fat":      {"current": 48,   "target": 55,   "unit": "g"},
        "passed":   False,
        "message":  "목표 영양소를 충족하지 못했어요. 아래 경고를 확인해 주세요.",
        "warnings": ["단백질이 목표(120g)에 미달해요...", "칼로리가 목표(1700kcal) 대비 부족해요..."],
    },

    # recipe_agent 결과 그대로 유지 (execute_meal_plan 제거로 오염 없음)
    "selected_recipes": [rcp_1, rcp_2, rcp_3],

    "logs": [
        {"node": "meal", "event": "plan_created",      "plan_summary": {...}},
        {"node": "meal", "event": "nutrition_verified", "result": {...}},
        # plan_executed 이벤트 제거됨 (execute_meal_plan 삭제)
    ],
}
```

---

## UI 출력 결과

### MealPlanCard

```
📅 3일 식단 플랜
임박 재료를 앞쪽 일자에 배치했어요.

1일차  ← 임박 재료 집중 배치
  ⭐ 아침  브로콜리 계란 스크램블
  ⭐ 점심  닭가슴살 두부 강된장 덮밥
  ⭐ 저녁  닭가슴살 두부 스테이크

2일차
     아침  그릭요거트 + 방울토마토
  ⭐ 점심  닭가슴살 두부 강된장 덮밥
  ⭐ 저녁  브로콜리 계란 스크램블

3일차
  ⭐ 아침  계란 현미 주먹밥
  ⭐ 점심  닭가슴살 두부 스테이크
     저녁  닭가슴살 채소 볶음

⭐ = usesPriorityItem: true (임박 재료 포함)
```

### NutritionCard

```
💪 영양 검증  ❌ FAIL

단백질   ██████████░░  115 / 120g
칼로리   ███████░░░░░  1210 / 1700kcal
탄수화물 ████░░░░░░░░  58 / 150g
지방     █████████░░░  48 / 55g

목표 영양소를 충족하지 못했어요. 아래 경고를 확인해 주세요.

⚠️ 단백질이 목표(120g)에 미달해요. 닭가슴살·두부를 추가하면 좋아요.
⚠️ 칼로리가 목표(1700kcal) 대비 부족해요. 한 끼 분량을 늘려보세요.
```

---

## 함수 목록

| 함수 | LLM | RAG | 역할 |
|------|-----|-----|------|
| `meal_agent()` | ✅ 간접 | ❌ | 전체 오케스트레이션 |
| `create_weekly_plan()` | ✅ 직접 | ❌ | 3일 식단 계획 생성 (LLM 1회) |
| `_mark_priority_items()` | ❌ | ❌ | usesPriorityItem 자동 보정 |
| ~~`execute_meal_plan()`~~ | ~~❌~~ | ~~✅~~  | **삭제됨** — RAG 9회 호출 + 영양 오염 문제 |
| `_extract_constraints()` | ❌ | ❌ | user_input 키워드 추출 (shopping_agent 공유) |
| `verify_nutrition_goal()` | ❌ | ❌ | 영양 합산 + 목표 검증 |
| `_build_warnings()` | ❌ | ❌ | 한국어 경고 문장 생성 |
| `_build_message()` | ❌ | ❌ | 한국어 요약 메시지 생성 |
| `_summarize_plan()` | ❌ | ❌ | 로그용 plan 요약 |

---

## 테스트 실행 방법

```powershell
cd D:\07.Coding\ku_agent\FridgeMate\backend
python tests/test_meal_agent.py
```

### STEP별 서버 요구사항

| STEP | 설명 | LM Studio | ChromaDB |
|------|------|-----------|----------|
| STEP 1 | `_mark_priority_items()` | ❌ | ❌ |
| STEP 2 | `_extract_constraints()` | ❌ | ❌ |
| STEP 3 | `verify_nutrition_goal()` | ❌ | ❌ |
| STEP 4 | `create_weekly_plan()` | ✅ 필요 | ❌ |
| STEP 5 | `selected_recipes` 오염 없음 확인 | ✅ 필요 | ❌ |
| STEP 6 | `meal_agent()` 전체 | ✅ 필요 | ❌ |
| STEP 7 | `meal_agent()` fallback | ✅ 필요 | ❌ |