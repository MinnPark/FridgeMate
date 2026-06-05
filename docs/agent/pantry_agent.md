# Pantry Agent

> 냉장고 재료를 분석하여 유통기한 우선순위를 계산하는 에이전트

---

## 역할

- 프론트엔드에서 전달받은 구조화된 재료 목록(`ingredient_entries`)을 파싱
- 유통기한 기반으로 우선순위(`expiry_priority`) 계산
- 다른 Agent들이 사용하는 `pantry_items` 생성
- UI PantryCard가 사용하는 `pantry_analysis` 생성

---

## 관련 파일

```
backend/app/
├── agents/
│   └── pantry_agent.py       ← 메인 에이전트 로직
├── tools/
│   └── pantry_tools.py       ← 파싱 + 우선순위 계산 함수
└── graph/
    ├── state.py              ← pantry_items, pantry_analysis 필드 포함
    └── orchestrator.py       ← 첫 번째 노드로 등록
```

---

## 데이터 흐름

```
프론트엔드 (IngredientEntry[])
        ↓ POST /chat
main.py (ChatRequest.ingredient_entries)
        ↓ graph.invoke()
pantry_agent
  ├── build_pantry_items()    → pantry_items    (meal/shopping agent 용)
  └── build_pantry_analysis() → pantry_analysis (UI PantryCard 용)
        ↓
meal_agent / recipe_agent
```

---

## Input

### 프론트엔드 → 백엔드 (`POST /chat`)

```json
{
  "message": "냉장고에 닭가슴살, 계란, 브로콜리, 두부 있어. 고단백 저탄수 식단 짜줘",
  "budget_limit": 100000,
  "ingredient_entries": [
    { "name": "닭가슴살", "amount": "500g",  "expiration_date": "2026-06-10", "storage_type": "냉장 보관" },
    { "name": "계란",     "amount": "10개",  "expiration_date": "2026-06-07", "storage_type": "냉장 보관" },
    { "name": "브로콜리", "amount": "300g",  "expiration_date": "2026-06-08", "storage_type": "냉장 보관" },
    { "name": "두부",     "amount": "1모",   "expiration_date": "2026-06-06", "storage_type": "냉장 보관" }
  ]
}
```

| 필드 | 타입 | 설명 |
|------|------|------|
| `name` | `str` | 재료 이름 |
| `amount` | `str \| None` | 용량 (예: "500g", "10개") |
| `expiration_date` | `str \| None` | 유통기한 `"YYYY-MM-DD"` |
| `storage_type` | `str \| None` | 보관 방법 (예: "냉장 보관") |

---

## Output

### 1. `pantry_items` - meal / shopping agent 용

```json
[
  { "name": "닭가슴살", "amount": 500.0, "unit": "g",  "expiry_priority": "normal", "expiration_date": "2026-06-10", "storage_type": "냉장 보관" },
  { "name": "계란",     "amount": 10.0,  "unit": "개", "expiry_priority": "high",   "expiration_date": "2026-06-07", "storage_type": "냉장 보관" },
  { "name": "브로콜리", "amount": 300.0, "unit": "g",  "expiry_priority": "high",   "expiration_date": "2026-06-08", "storage_type": "냉장 보관" },
  { "name": "두부",     "amount": 1.0,   "unit": "모", "expiry_priority": "high",   "expiration_date": "2026-06-06", "storage_type": "냉장 보관" }
]
```

| 필드 | 타입 | 설명 |
|------|------|------|
| `name` | `str` | 재료 이름 |
| `amount` | `float \| None` | 숫자 용량 |
| `unit` | `str \| None` | 단위 (g, 개, 모 등) |
| `expiry_priority` | `"high" \| "normal"` | 유통기한 우선순위 |
| `expiration_date` | `str \| None` | 유통기한 원본 |
| `storage_type` | `str \| None` | 보관 방법 |

---

### 2. `pantry_analysis` - UI PantryCard 용

```json
{
  "items": [
    { "name": "닭가슴살", "category": "재료", "freshness": "soon",   "amount": "500g", "expiry_label": "5일 남음", "note": "냉장 보관" },
    { "name": "계란",     "category": "재료", "freshness": "urgent", "amount": "10개", "expiry_label": "2일 남음", "note": "냉장 보관" },
    { "name": "브로콜리", "category": "재료", "freshness": "urgent", "amount": "300g", "expiry_label": "3일 남음", "note": "냉장 보관" },
    { "name": "두부",     "category": "재료", "freshness": "urgent", "amount": "1모",  "expiry_label": "1일 남음", "note": "냉장 보관" }
  ],
  "priority_use": ["계란", "브로콜리", "두부"],
  "summary": "유통기한이 가까운 계란, 브로콜리, 두부을(를) 우선 사용하는 식단을 구성할게요."
}
```

| 필드 | 타입 | 설명 |
|------|------|------|
| `items[].freshness` | `"fresh" \| "soon" \| "urgent"` | UI 색상 표시용 |
| `items[].expiry_label` | `str \| None` | UI 표시 문구 |
| `priority_use` | `str[]` | 우선 사용 재료 목록 |
| `summary` | `str` | UI 요약 문구 |

---

## 유통기한 계산 로직

| 남은 일수 | `expiry_priority` | `freshness` | 의미 |
|----------|-------------------|-------------|------|
| 날짜 없음 | `normal` | `fresh` | 유통기한 미입력 |
| 0일 이하 | `high` | `urgent` | 만료됨 |
| 1 ~ 3일 | `high` | `urgent` | 임박 (우선 사용) |
| 4 ~ 7일 | `normal` | `soon` | 여유 있음 |
| 8일 이상 | `normal` | `fresh` | 신선 |

---

## 테스트 실행

```powershell
cd backend
python test_pantry_agent.py
```

### 테스트 항목

| Step | 검증 내용 |
|------|----------|
| STEP 1 | `parse_amount_unit()` - "500g" → (500.0, "g") |
| STEP 2 | `calculate_days_left()` - 날짜 → 남은 일수 |
| STEP 3 | `expiry_priority` + `freshness` 계산 |
| STEP 4 | `build_pantry_items()` - 다른 agent용 포맷 |
| STEP 5 | `build_pantry_analysis()` - UI용 포맷 |
| STEP 6 | `pantry_agent()` - 전체 state 반환 |

---

## 다음 Agent 연계

`pantry_items`의 `expiry_priority` 필드를 다음 agent들이 활용합니다:

- **meal_agent**: `expiry_priority == "high"` 재료를 우선 포함한 식단 구성
- **shopping_agent**: `pantry_items`와 레시피 재료 비교 → 부족 재료 계산