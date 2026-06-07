# shopping_agent.py 개발 문서

> 작성일: 2026-06-07  
> 담당: 전영주  
> 관련 파일: `app/agents/shopping_agent.py`, `app/tools/shopping_tools.py`, `app/graph/state.py`

---

## 개요

`shopping_agent`는 FridgeMate 파이프라인의 **4번째 에이전트**다.  
`meal_agent`가 확정한 식단과 `recipe_agent`가 검색한 레시피를 바탕으로  
**실제 구매가 필요한 부족 재료 목록을 계산**한다.

```
pantry_agent (1) → recipe_agent (2) → meal_agent (3) → shopping_agent (4) → executor_agent (5)
```

> **이 에이전트는 LLM / RAG / 외부 API를 일절 호출하지 않는다.**  
> 순수 계산 로직만 수행하므로 서버 없이 테스트 가능하다.

---

## 역할 범위

```
shopping_agent 담당                   Coupang 팀 담당
────────────────────────────────────────────────────────────
meal_plan + selected_recipes           missing_ingredients
+ pantry_items                       → 쿠팡 상품 검색
→ missing_ingredients 계산            → product_url, price
(LLM/RAG 없음, 순수 계산)             → cart_items 완성
```

---

## 입력 / 출력

### 입력 (`FridgeMateState`)

| 키 | 출처 | 설명 |
|----|------|------|
| `meal_plan` | `meal_agent` | 3일 × 3끼 식단 계획 (label/entries 형식) |
| `selected_recipes` | `recipe_agent` | RAG 검색 레시피 + 재료 목록 + 영양 정보 |
| `pantry_items` | `pantry_agent` | 냉장고 보유 재료 목록 |

### 출력 (`FridgeMateState`)

| 키 | 사용처 | 설명 |
|----|--------|------|
| `missing_ingredients` | **Coupang 팀 → `cart_items`** | 부족 재료 목록 (이름 오름차순) |
| `logs` | UI `AgentPipelinePanel` | `missing_calculated` 이벤트 로그 |

#### `missing_ingredients` 구조

```python
[
    {
        "name":      str,           # 재료명
        "amount":    float | None,  # 식단 전체 필요량 (사용 횟수 × 1회 분량)
        "unit":      str | None,    # g, 개, ml, ... / 없으면 None
        "needed_by": [str],         # 이 재료가 필요한 레시피 이름 목록
    },
    ...
]
```

---

## 전체 실행 흐름

```
shopping_agent(state)
    │
    ├── STEP A: _collect_used_recipes()
    │     meal_plan 식단에서 실제 사용된 recipeTitle + 사용 횟수 추출
    │     → selected_recipes name 매핑
    │     → [{"title", "count", "ingredients"}]
    │
    ├── STEP B: _aggregate_ingredients()
    │     레시피별 재료를 이름 기준으로 합산
    │     사용 횟수(count)만큼 amount 배수 적용
    │     → {"이름||unit": {"name", "amount", "unit", "needed_by"}}
    │
    ├── STEP C: _calc_missing()
    │     집계된 재료 중 pantry_items에 없는 것만 필터링
    │     이름 오름차순 정렬
    │     → [{"name", "amount", "unit", "needed_by"}]
    │
    └── return state
          ├── missing_ingredients  ← STEP C 결과
          └── logs                 ← missing_calculated 이벤트
```

---

## 테스트 시나리오 입력 데이터

```python
# 냉장고 보유 재료 (오늘: 2026-06-07)
pantry_items = [
    {"name": "닭가슴살", "expiry_priority": "normal", "expiration_date": "2026-06-10"},  # D+3
    {"name": "계란",     "expiry_priority": "high",   "expiration_date": "2026-06-07"},  # D+0 ⚠️
    {"name": "브로콜리", "expiry_priority": "high",   "expiration_date": "2026-06-08"},  # D+1
    {"name": "두부",     "expiry_priority": "high",   "expiration_date": "2026-06-06"},  # D-1 ⚠️
]

# recipe_agent 검색 레시피
selected_recipes = [
    {
        "id":   "rcp_1",
        "name": "닭가슴살 두부 강된장 덮밥",
        "ingredients": [
            {"name": "닭가슴살", "amount": 200, "unit": "g"},
            {"name": "두부",     "amount": 150, "unit": "g"},
            {"name": "양파",     "amount": 100, "unit": "g"},   # ← 냉장고에 없음
            {"name": "된장",     "amount": 30,  "unit": "g"},   # ← 냉장고에 없음
            {"name": "현미밥",   "amount": 200, "unit": "g"},   # ← 냉장고에 없음
        ],
    },
    {
        "id":   "rcp_2",
        "name": "브로콜리 계란 스크램블",
        "ingredients": [
            {"name": "브로콜리",   "amount": 150, "unit": "g"},
            {"name": "계란",       "amount": 2,   "unit": "개"},
            {"name": "올리브오일", "amount": 10,  "unit": "ml"}, # ← 냉장고에 없음
            {"name": "소금",       "amount": 2,   "unit": "g"},  # ← 냉장고에 없음
        ],
    },
    {
        "id":   "rcp_3",
        "name": "닭가슴살 두부 스테이크",
        "ingredients": [
            {"name": "닭가슴살", "amount": 200,  "unit": "g"},
            {"name": "두부",     "amount": 100,  "unit": "g"},
            {"name": "파프리카", "amount": 100,  "unit": "g"},   # ← 냉장고에 없음
            {"name": "허브",     "amount": None, "unit": None},  # ← amount=None 엣지케이스
        ],
    },
]

# meal_agent 생성 식단 (3일 × 3끼)
meal_plan = {
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
                {"slot": "아침", "recipeTitle": "그릭요거트 + 방울토마토",   "usesPriorityItem": False},  # ← selected_recipes에 없음
                {"slot": "점심", "recipeTitle": "닭가슴살 두부 강된장 덮밥", "usesPriorityItem": True},
                {"slot": "저녁", "recipeTitle": "브로콜리 계란 스크램블",    "usesPriorityItem": True},
            ],
        },
        {
            "label": "3일차",
            "entries": [
                {"slot": "아침", "recipeTitle": "계란 현미 주먹밥",          "usesPriorityItem": True},   # ← selected_recipes에 없음
                {"slot": "점심", "recipeTitle": "닭가슴살 두부 스테이크",    "usesPriorityItem": True},
                {"slot": "저녁", "recipeTitle": "닭가슴살 채소 볶음",        "usesPriorityItem": False},  # ← selected_recipes에 없음
            ],
        },
    ],
}
```

---

## STEP A: `_collect_used_recipes()` — 사용 레시피 + 횟수 추출

### 역할

`meal_plan.days[].entries[].recipeTitle`을 순회해  
**레시피별 사용 횟수를 집계**하고 `selected_recipes`에서 재료 목록을 매핑한다.

### 데이터 변환 과정

**① recipeTitle 사용 횟수 집계**

```
meal_plan 9개 끼니를 순회:

1일차 아침  → "브로콜리 계란 스크램블"    count +1
1일차 점심  → "닭가슴살 두부 강된장 덮밥" count +1
1일차 저녁  → "닭가슴살 두부 스테이크"    count +1
2일차 아침  → "그릭요거트 + 방울토마토"   count +1
2일차 점심  → "닭가슴살 두부 강된장 덮밥" count +1  ← 2번째
2일차 저녁  → "브로콜리 계란 스크램블"    count +1  ← 2번째
3일차 아침  → "계란 현미 주먹밥"          count +1
3일차 점심  → "닭가슴살 두부 스테이크"    count +1  ← 2번째
3일차 저녁  → "닭가슴살 채소 볶음"        count +1

title_counts = {
    "닭가슴살 두부 강된장 덮밥": 2,
    "브로콜리 계란 스크램블":    2,
    "닭가슴살 두부 스테이크":    2,
    "그릭요거트 + 방울토마토":   1,   ← selected_recipes에 없음
    "계란 현미 주먹밥":          1,   ← selected_recipes에 없음
    "닭가슴살 채소 볶음":        1,   ← selected_recipes에 없음
}
```

**② 매핑 결과**

```python
used_recipes = [
    {"title": "계란 현미 주먹밥",          "count": 1, "ingredients": []},  # ⚠️ 매핑 실패
    {"title": "그릭요거트 + 방울토마토",   "count": 1, "ingredients": []},  # ⚠️ 매핑 실패
    {"title": "닭가슴살 두부 강된장 덮밥", "count": 2, "ingredients": [...]},
    {"title": "닭가슴살 두부 스테이크",    "count": 2, "ingredients": [...]},
    {"title": "닭가슴살 채소 볶음",        "count": 1, "ingredients": []},  # ⚠️ 매핑 실패
    {"title": "브로콜리 계란 스크램블",    "count": 2, "ingredients": [...]},
]

warnings = [
    "'계란 현미 주먹밥' → selected_recipes에 없음 (ingredients 빈값 처리)",
    "'그릭요거트 + 방울토마토' → selected_recipes에 없음 (ingredients 빈값 처리)",
    "'닭가슴살 채소 볶음' → selected_recipes에 없음 (ingredients 빈값 처리)",
]
```

> **⚠️ 엣지케이스 처리**  
> LLM이 `selected_recipes` 목록 외 레시피를 생성했을 때 → `ingredients=[]`로 처리 + warning 기록

---

## STEP B: `_aggregate_ingredients()` — 재료 집계 + 사용 횟수 배수 적용

```
닭가슴살 두부 강된장 덮밥 (count=2):
  양파    100g × 2 = 200g  /  된장  30g × 2 = 60g  /  현미밥 200g × 2 = 400g

브로콜리 계란 스크램블 (count=2):
  올리브오일 10ml × 2 = 20ml  /  소금 2g × 2 = 4g

닭가슴살 두부 스테이크 (count=2):
  파프리카 100g × 2 = 200g  /  허브 None × 2 = None  ← amount=None 유지
```

> **⚠️ 엣지케이스**
>
> | 상황 | 처리 방식 |
> |------|-----------|
> | **같은 재료, 다른 단위** | `"재료||g"` vs `"재료||개"` 별도 키 → Coupang 팀이 판단 |
> | **amount=None** | `None` 유지 → Coupang 팀이 기본 수량으로 검색 |
> | **unit=""(빈 문자열)** | `None`으로 정규화 |

---

## STEP C: `_calc_missing()` — 냉장고 비교 → 부족 재료 추출

> **양 비교는 지원하지 않는다.**  
> "이름이 있으면 보유"로 단순 처리 — pantry amount 신뢰도 낮음(단위 불일치·오탈자 등)

```
pantry_names = {닭가슴살, 계란, 브로콜리, 두부}

aggregated 재료 11개 중 pantry에 없는 7개 → missing
```

**최종 `missing_ingredients` (이름 오름차순)**

```python
missing_ingredients = [
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

## LLM 응답 정규화 함수 (UI 연동 버그 수정)

> UI 연동 테스트에서 발견된 버그 2종을 수정하기 위해 추가된 함수들

### 버그 1: 재료명 띄어쓰기 → 다른 재료로 인식

```
"닭  가슴살" (LLM 응답)  vs  "닭가슴살" (pantry)
→ .strip()만으로는 내부 공백 처리 불가 → 다른 재료로 인식 → missing에 포함되는 문제
```

#### `_normalize_name()` — 재료명 정규화

```python
_normalize_name("닭  가슴살")  → "닭 가슴살"   # 중복 공백 제거
_normalize_name(" 브로콜리 ")  → "브로콜리"    # 앞뒤 공백 제거
_normalize_name("닭\t가슴살")  → "닭 가슴살"   # 탭 → 공백
```

> 적용 위치: `_collect_used_recipes()`, `_aggregate_ingredients()`, `_calc_missing()` 전 함수

---

### 버그 2: "12g+3", "6작은술" 형태 출력

```
원인: LLM이 unit 필드에 "g+3" 같은 잘못된 값 반환
      → _format_quantity(12, "g+3") = "12g+3"  ← 비정상 출력

또는: LLM이 amount 필드에 "6작은술" 같은 문자열 반환
      → amount * count = "6작은술6작은술"  ← 문자열 반복
```

#### `_parse_amount()` — amount 안전 파싱

```python
_parse_amount(12)          → 12.0    # 정수
_parse_amount("12")        → 12.0    # 숫자 문자열
_parse_amount("12g")       → 12.0    # 단위 혼입
_parse_amount("12g+3")     → 12.0    # 복합 표현 → 선두 숫자만 추출
_parse_amount("6작은술")   → 6.0     # 한글 단위 혼입
_parse_amount("1~2")       → 1.0     # 범위 → 최솟값
_parse_amount("약간")      → None    # 파싱 불가
_parse_amount(None)        → None
```

#### `_normalize_unit()` — unit 정규화

```python
_normalize_unit("g")       → "g"     # 정상
_normalize_unit("g+3")     → "g"     # 특수문자 제거
_normalize_unit("g/개")    → "g"     # 슬래시 앞 단위만 사용
_normalize_unit("ml ")     → "ml"    # 공백 제거
_normalize_unit("")        → None
_normalize_unit(None)      → None
```

---

## `_format_quantity()` — Coupang 팀 quantity 포맷

```python
_format_quantity(200,  "g")   → "200g"
_format_quantity(1.5,  "kg")  → "1.5kg"
_format_quantity(3.0,  "개")  → "3개"     # 정수형 소수 → 정수로 변환
_format_quantity(3,    None)  → "3"       # 단위 없음
_format_quantity(None, "g")   → None      # amount 없음 → Coupang 팀이 기본 수량으로 검색
_format_quantity(None, None)  → None
```

---

## 최종 반환 state

```python
{
    **state,
    "missing_ingredients": [ ... ],   # 7개, 이름 오름차순
    "logs": [
        {
            "node":  "shopping",
            "event": "missing_calculated",
            "result": {
                "used_recipe_count": 6,
                "aggregated_count":  11,
                "missing_count":     7,
                "missing_names":     ["된장", "소금", "양파", "올리브오일", "파프리카", "허브", "현미밥"],
                "warnings": [
                    "'계란 현미 주먹밥' → selected_recipes에 없음 (ingredients 빈값 처리)",
                    "'그릭요거트 + 방울토마토' → selected_recipes에 없음 (ingredients 빈값 처리)",
                    "'닭가슴살 채소 볶음' → selected_recipes에 없음 (ingredients 빈값 처리)",
                ],
            },
        }
    ],
}
```

---

## Coupang 팀 인수 인계 계약

### 입력: `missing_ingredients`

```python
# Coupang 팀이 읽는 필드
missing_ingredients[].name       → search_coupang_products() 검색 키워드
missing_ingredients[].amount     → _format_quantity(amount, unit) → quantity 문자열
missing_ingredients[].unit       → _format_quantity(amount, unit) → quantity 문자열
missing_ingredients[].needed_by  → ShoppingCard UI 표시용
```

### 주의사항

```
⚠️  amount=None 인 재료 반드시 처리 필요
    예) 허브 → amount=None, unit=None
    → _format_quantity(None, None) = None
    → 쿠팡 검색 시 기본 수량(1개 등)으로 fallback 처리 권장

⚠️  needed_by는 1개 재료가 여러 레시피에 걸칠 수 있음
    예) 닭가슴살 두부 강된장 덮밥 + 닭가슴살 두부 스테이크 → needed_by 리스트 2개
    → UI ShoppingCard에서 레시피 복수 표시 처리 필요

⚠️  missing_ingredients는 이름 오름차순 정렬 보장
    → UI 렌더링 순서 별도 정렬 불필요

⚠️  warnings 로그 확인 권장
    selected_recipes에 없는 recipeTitle → 재료 미집계
    → 해당 끼니 재료는 cart_items에 포함되지 않음
```

### 출력: `cart_items` 구조

```python
cart_items = [
    {
        "ingredient":    str,         # missing_ingredients[].name
        "product_name":  str,         # 쿠팡 상품명
        "quantity":      str | None,  # _format_quantity(amount, unit) 결과
        "price":         int | None,  # 쿠팡 상품 가격
        "deeplink":      str | None,  # 쿠팡 상품 URL
    },
    ...
]
```

### `search_coupang_products()` 호출 예시

```python
from app.tools.shopping_tools import search_coupang_products, create_cart_deeplinks
from app.agents.shopping_agent import _format_quantity

# state에서 missing_ingredients 읽기
missing = state["missing_ingredients"]

# 쿠팡 상품 검색
products = search_coupang_products(missing)

# deeplink 생성
cart_items = create_cart_deeplinks(products)
```

---

## 함수 목록

| 함수 | 위치 | 역할 |
|------|------|------|
| `shopping_agent()` | `shopping_agent.py` | 전체 오케스트레이션 |
| `_normalize_name()` | `shopping_agent.py` | 재료명 띄어쓰기 정규화 |
| `_parse_amount()` | `shopping_agent.py` | LLM amount 문자열 안전 파싱 |
| `_normalize_unit()` | `shopping_agent.py` | LLM unit 문자열 정규화 |
| `_collect_used_recipes()` | `shopping_agent.py` | STEP A — 사용 레시피 + 횟수 추출 |
| `_aggregate_ingredients()` | `shopping_agent.py` | STEP B — 재료 집계 + count 배수 |
| `_calc_missing()` | `shopping_agent.py` | STEP C — 냉장고 비교 → 부족 재료 필터 |
| `_format_quantity()` | `shopping_agent.py` | quantity 포맷 변환 **(Coupang 팀 사용)** |
| `search_coupang_products()` | `shopping_tools.py` | 쿠팡 상품 검색 **(Coupang 팀)** |
| `create_cart_deeplinks()` | `shopping_tools.py` | deeplink 생성 **(Coupang 팀)** |
| `validate_budget()` | `shopping_tools.py` | 예산 검증 **(Coupang 팀)** |

> 전 함수 LLM / RAG / 외부 API 호출 없음 — 서버 불필요

---

## 테스트 실행 방법

```powershell
cd D:\07.Coding\ku_agent\FridgeMate\backend
python tests/test_shopping_agent.py
```

> **서버 불필요** — LM Studio / ChromaDB 없이 전체 STEP 실행 가능 🎉  
> `shopping_agent()` 단일 함수만 호출 — 내부 함수 직접 노출 없음

### 테스트 STEP 구성 (`test_shopping_agent.py`)

| STEP | 검증 항목 |
|------|-----------|
| STEP 1 | `shopping_agent()` 정상 실행 — state 구조 검증 |
| STEP 2 | pantry 재료 제외 검증 |
| STEP 3 | 미보유 재료 포함 검증 |
| STEP 4 | `needed_by` 유효성 검증 |
| STEP 5 | 이름 오름차순 정렬 검증 |
| STEP 6 | log(`missing_calculated`) 구조 검증 |
| STEP 7 | 엣지케이스: `pantry_items=[]` |
| STEP 8 | 엣지케이스: `meal_plan={}` |
| STEP 9 | `_format_quantity()` 출력 테스트 |
| STEP 10 | 재료명 띄어쓰기 정규화 검증 |