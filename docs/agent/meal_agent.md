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
| `selected_recipes` | `recipe_agent` | RAG 검색된 레시피 상위 **9개** ← 3→9 변경 |
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
| `nutrition_result` | UI `NutritionCard` | 영양 **하루 평균** + 목표 검증 결과 ← 변경 |
| `selected_recipes` | `shopping_agent` | **recipe_agent 결과 그대로 유지 (오염 없음)** |
| `logs` | UI `AgentPipelinePanel` | 실행 이벤트 로그 |

---

## 전체 실행 흐름

```
meal_agent(state)
    │
    ├── 1. create_weekly_plan(state)              ← LLM 1회 호출
    │       ├── _sort_recipes_by_slot()           ← 칼로리 기준 슬롯 분류 (신규)
    │       ├── generate_json()                   ← LLM 호출 (슬롯별 추천 목록 포함)
    │       ├── _ensure_unique_recipes()          ← 중복 제거 / 허용 목록 보정 (신규)
    │       ├── _mark_priority_items()            ← usesPriorityItem 자동 보정
    │       └── _apply_slot_calories()            ← 칼로리 기준 후처리 보정 (신규)
    │
    ├── 2. verify_nutrition_goal()                ← 영양 합산 계산 (LLM 없음, RAG 없음)
    │       ├── 9개 레시피 전체 합산
    │       ├── ÷ num_days(3) → 하루 평균 계산    ← 변경
    │       ├── _build_warnings()                 ← 한국어 경고 문장 생성
    │       └── _build_message()                  ← 한국어 요약 메시지 생성
    │
    └── 3. return state
            ├── meal_plan
            ├── nutrition_result                  ← 하루 평균 기준
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

## 테스트 시나리오 (오늘: 2026-06-07)

### 입력 데이터

```python
# 냉장고 재료
TEST_PANTRY_ITEMS = [
    {"name": "닭가슴살", "expiry_priority": "normal", "expiration_date": "2026-06-10"},  # D+3
    {"name": "계란",     "expiry_priority": "high",   "expiration_date": "2026-06-08"},  # D+1
    {"name": "브로콜리", "expiry_priority": "high",   "expiration_date": "2026-06-09"},  # D+2
    {"name": "두부",     "expiry_priority": "high",   "expiration_date": "2026-06-07"},  # D+0 ⚠️
]

# recipe_agent가 검색한 레시피 (9개) ← 3→9 변경
TEST_SELECTED_RECIPES = [
    {"id": "rcp_1", "name": "두부오믈렛",              "nutrition": {"calories": 280, "protein": 22, "carbs": 12, "fat": 18}},
    {"id": "rcp_2", "name": "브로콜리 계란 스크램블",   "nutrition": {"calories": 310, "protein": 24, "carbs": 14, "fat": 16}},
    {"id": "rcp_3", "name": "두부곤약조림",             "nutrition": {"calories": 250, "protein": 18, "carbs": 10, "fat": 12}},
    {"id": "rcp_4", "name": "닭가슴살 두부 강된장 덮밥","nutrition": {"calories": 520, "protein": 45, "carbs": 38, "fat": 14}},
    {"id": "rcp_5", "name": "닭가슴살 브로콜리 볶음",   "nutrition": {"calories": 490, "protein": 48, "carbs": 16, "fat": 18}},
    {"id": "rcp_6", "name": "닭가슴살 두부 스테이크",   "nutrition": {"calories": 410, "protein": 48, "carbs": 8,  "fat": 16}},
    {"id": "rcp_7", "name": "두부 된장찌개",            "nutrition": {"calories": 350, "protein": 28, "carbs": 22, "fat": 14}},
    {"id": "rcp_8", "name": "계란 현미 주먹밥",         "nutrition": {"calories": 380, "protein": 18, "carbs": 52, "fat": 10}},
    {"id": "rcp_9", "name": "브로콜리 두부 샐러드",     "nutrition": {"calories": 210, "protein": 16, "carbs": 18, "fat": 8}},
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

`selected_recipes`(9개)와 `pantry_items`를 LLM에 전달해  
**3일 × 3끼 식단 계획 JSON**을 생성한다. **(LLM 1회만 호출)**

### 칼로리 기준 슬롯 분류 (`_sort_recipes_by_slot()`) ← 신규

9개 레시피를 칼로리 기준으로 3등분해 슬롯별 추천 목록을 만든다.

```
9개 레시피 칼로리 오름차순 정렬
  브로콜리 두부 샐러드    210kcal  ┐
  두부오믈렛             280kcal  ├─ 하위 3개 → 아침 (morning_titles)
  두부곤약조림           250kcal  ┘
  두부 된장찌개          350kcal  ┐
  계란 현미 주먹밥        380kcal  ├─ 중간 3개 → 저녁 (dinner_titles)
  브로콜리 계란 스크램블  310kcal  ┘
  닭가슴살 두부 스테이크  410kcal  ┐
  닭가슴살 두부 강된장    520kcal  ├─ 상위 3개 → 점심 (lunch_titles)
  닭가슴살 브로콜리 볶음  490kcal  ┘
```

### LLM에 전달하는 user_prompt

```
사용자 요청: 냉장고에 계란, 브로콜리, 두부 있어. 고단백 저탄수. 2인분...
냉장고 재료: ['닭가슴살', '계란', '브로콜리', '두부']
유통기한 임박 재료(priority_items): ['계란', '브로콜리', '두부']
선택된 레시피 목록(반드시 이 목록에서만 선택): ['두부오믈렛', '브로콜리 계란 스크램블', ...]
영양 목표: {'protein_target': 120, 'calorie_target': 1700, ...}
아침 슬롯 추천 레시피(칼로리 낮은 순): ['브로콜리 두부 샐러드', '두부오믈렛', '두부곤약조림']
점심 슬롯 추천 레시피(칼로리 높은 순): ['닭가슴살 두부 스테이크', '닭가슴살 두부 강된장 덮밥', '닭가슴살 브로콜리 볶음']
저녁 슬롯 추천 레시피(칼로리 중간):   ['두부 된장찌개', '계란 현미 주먹밥', '브로콜리 계란 스크램블']
```

### meal_prompts.py 슬롯별 배치 규칙 ← 변경

```
규칙 5: 9개 레시피를 3일 × 3끼 = 9개 슬롯에 각각 1번씩만 배치 (중복 사용 금지)
규칙 6: 슬롯별 칼로리 배치 기준 반드시 준수
  - 아침: morning_recipes 목록에서 선택 (칼로리 낮은 것)
  - 점심: lunch_recipes  목록에서 선택 (칼로리 높은 것)
  - 저녁: dinner_recipes 목록에서 선택 (칼로리 중간)
```

### 후처리 순서 (중요)

```
1. _ensure_unique_recipes()   ← 중복 제거 / 허용 목록 보정
2. _mark_priority_items()     ← priority 재료 포함 끼니 표시
3. _apply_slot_calories()     ← 칼로리 기준 슬롯 보정 (swap 방식)
```

### LLM 실패 시 fallback

LLM 호출이 실패하거나 JSON 파싱 오류 발생 시 `selected_recipes` 인덱스 0~8 순서대로 자동 배치한다.

```python
fallback = {
    "note": "임박 재료를 앞쪽 일자에 배치했어요.",
    "days": [
        {"label": "1일차", "entries": [
            {"slot": "아침", "recipeTitle": recipes[0], "usesPriorityItem": True},
            {"slot": "점심", "recipeTitle": recipes[1], "usesPriorityItem": True},
            {"slot": "저녁", "recipeTitle": recipes[2], "usesPriorityItem": True},
        ]},
        {"label": "2일차", "entries": [
            {"slot": "아침", "recipeTitle": recipes[3], "usesPriorityItem": False},
            {"slot": "점심", "recipeTitle": recipes[4], "usesPriorityItem": False},
            {"slot": "저녁", "recipeTitle": recipes[5], "usesPriorityItem": False},
        ]},
        {"label": "3일차", "entries": [
            {"slot": "아침", "recipeTitle": recipes[6], "usesPriorityItem": False},
            {"slot": "점심", "recipeTitle": recipes[7], "usesPriorityItem": False},
            {"slot": "저녁", "recipeTitle": recipes[8], "usesPriorityItem": False},
        ]},
    ],
}
```

---

## STEP 1-1: `_sort_recipes_by_slot()` — 칼로리 기준 슬롯 분류 ← 신규

### 역할

9개 레시피를 칼로리 오름차순 정렬 후 3등분해 아침/점심/저녁 슬롯 추천 목록을 반환한다.

### 규칙

```
nutrition 없는 레시피 → calories=0 간주 → 아침 슬롯 우선
recipes 빈 리스트     → ([], [], []) 반환
```

### 반환값

| 반환 | 설명 |
|------|------|
| `morning_titles` | 칼로리 낮은 순 3개 이름 |
| `lunch_titles`   | 칼로리 높은 순 3개 이름 |
| `dinner_titles`  | 칼로리 중간 3개 이름   |

---

## STEP 1-2: `_ensure_unique_recipes()` — 중복 제거 ← 신규

### 역할

9개 레시피를 9개 슬롯에 1:1 배치 보장.

### 처리 순서

```
1. 허용 목록 벗어난 recipeTitle → 미사용 레시피로 교체
2. 중복 recipeTitle              → 미사용 레시피로 교체
3. 미사용 레시피 소진 시          → 허용 목록 순환 (안전장치)
```

---

## STEP 1-3: `_mark_priority_items()` — usesPriorityItem 자동 보정

### 역할

LLM이 `usesPriorityItem`을 **누락하거나 잘못 표시한 경우** 자동으로 보정한다.  
`recipeTitle`에 `expiry_priority == "high"` 재료 이름이 포함되어 있으면 `true`로 설정한다.

### 보정 규칙

```
priority_names = ["계란", "브로콜리", "두부"]   ← expiry_priority == "high"

recipeTitle에 priority_names 중 하나라도 포함  →  usesPriorityItem = True
recipeTitle에 priority_names 없음              →  usesPriorityItem = False
```

---

## STEP 1-4: `_apply_slot_calories()` — 칼로리 기준 후처리 보정 ← 신규

### 역할

LLM이 잘못 배치한 경우 **swap 방식**으로 보정한다.

### 보정 규칙

```
아침 슬롯에 고칼로리(lunch_titles) 레시피 있으면
  → 다른 슬롯의 저칼로리(morning_titles) 레시피와 서로 swap

점심 슬롯에 저칼로리(morning_titles) 레시피 있으면
  → 다른 슬롯의 고칼로리(lunch_titles) 레시피와 서로 swap

우선순위:
  usesPriorityItem=True 이면 swap 건너뜀 (priority 1순위)
```

### swap 방식을 사용하는 이유

```
교체 방식 (변경 전):
  아침에 고칼로리 → morning_unused[0]으로 교체
  BUT morning_unused[0]이 이미 다른 슬롯에 배치된 것 → 중복 발생 ❌

swap 방식 (변경 후):
  아침 고칼로리 ↔ 다른 슬롯 저칼로리 서로 교환
  → 중복 없음 ✅
```

---

## STEP 2: `verify_nutrition_goal()` — 영양 합산 검증 ← 변경

### 역할

`selected_recipes` (9개)의 `nutrition` 값을 합산 후  
**일수(num_days=3)로 나눠 하루 평균**을 목표값과 비교한다.

### 계산 방식 변경

```
변경 전:
  9개 합산 그대로 목표와 비교
  → 총 칼로리 4500kcal vs 목표 1700kcal → 항상 초과 ❌

변경 후:
  9개 합산 ÷ 3(num_days) = 하루 평균
  → 하루 평균 1500kcal vs 목표 1700kcal → 정상 비교 ✅
```

### 합산 계산 (9개 레시피 → 하루 평균)

```
레시피                         calories  protein  carbs  fat
──────────────────────────────────────────────────────────────
두부오믈렛                       280       22       12     18
브로콜리 계란 스크램블             310       24       14     16
두부곤약조림                      250       18       10     12
닭가슴살 두부 강된장 덮밥           520       45       38     14
닭가슴살 브로콜리 볶음             490       48       16     18
닭가슴살 두부 스테이크             410       48        8     16
두부 된장찌개                     350       28       22     14
계란 현미 주먹밥                   380       18       52     10
브로콜리 두부 샐러드               210       16       18      8
──────────────────────────────────────────────────────────────
합계 (total_sum)               3,200      267      190    126
÷ 3 (하루 평균)                1,067       89       63     42

목표 (targets / 하루 기준)      1,700      120      150     55
```

### `passed` 판정 기준

```python
passed = (
    totals["protein"]  >= targets["protein"]             # 89 >= 120  → False ❌
    and totals["calories"] >= targets["calories"] * 0.9  # 1067 >= 1530 → False ❌
    and totals["calories"] <= targets["calories"] * 1.1  # 1067 <= 1870 → True  ✅
)
# → passed = False
```

### 최종 반환값 (`nutrition_result`)

```python
{
    "protein":  {"current": 89,   "target": 120,  "unit": "g"},
    "calories": {"current": 1067, "target": 1700, "unit": "kcal"},
    "carbs":    {"current": 63,   "target": 150,  "unit": "g"},
    "fat":      {"current": 42,   "target": 55,   "unit": "g"},
    "passed":   False,
    "message":  "목표 영양소를 충족하지 못했어요. 아래 경고를 확인해 주세요.",
    "warnings": [
        "단백질이 목표(120g)에 미달해요. 닭가슴살·두부를 추가하면 좋아요.",
        "칼로리가 목표(1700kcal) 대비 부족해요. 한 끼 분량을 늘려보세요.",
    ],
}
```

---

## 함수 목록

| 함수 | LLM | RAG | 역할 |
|------|-----|-----|------|
| `meal_agent()` | ✅ 간접 | ❌ | 전체 오케스트레이션 |
| `create_weekly_plan()` | ✅ 직접 | ❌ | 3일 식단 계획 생성 (LLM 1회) |
| `_sort_recipes_by_slot()` | ❌ | ❌ | 칼로리 기준 슬롯 분류 ← 신규 |
| `_ensure_unique_recipes()` | ❌ | ❌ | 9개 레시피 중복 제거 ← 신규 |
| `_mark_priority_items()` | ❌ | ❌ | usesPriorityItem 자동 보정 |
| `_apply_slot_calories()` | ❌ | ❌ | 칼로리 기준 슬롯 swap 보정 ← 신규 |
| ~~`execute_meal_plan()`~~ | ~~❌~~ | ~~✅~~ | **삭제됨** — RAG 9회 호출 + 영양 오염 문제 |
| `_extract_constraints()` | ❌ | ❌ | user_input 키워드 추출 |
| `verify_nutrition_goal()` | ❌ | ❌ | 영양 **하루 평균** + 목표 검증 ← 변경 |
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
| STEP 3 | `verify_nutrition_goal()` 하루 평균 계산 | ❌ | ❌ |
| STEP 4 | `_sort_recipes_by_slot()` 칼로리 분류 | ❌ | ❌ |
| STEP 5 | `_ensure_unique_recipes()` 중복 제거 | ❌ | ❌ |
| STEP 6 | `_apply_slot_calories()` swap 보정 | ❌ | ❌ |
| STEP 7 | `create_weekly_plan()` LLM 호출 | ✅ 필요 | ❌ |
| STEP 8 | `selected_recipes` 오염 없음 확인 | ✅ 필요 | ❌ |
| STEP 9 | `meal_agent()` 전체 | ✅ 필요 | ❌ |
| STEP 10 | `meal_agent()` fallback | ✅ 필요 | ❌ |