# FridgeMate AI — API 계약 (프론트엔드가 받을 데이터 형식)

> **목적**: 프론트엔드(역할 D)가 백엔드에 보내는 **요청**과, 백엔드로부터 받을 **응답**의 JSON 형식을 지정한다.
> 백엔드가 이 형식대로 내려주면 프론트는 그대로 화면에 표시한다.
>
> - **네이밍(casing)은 강제하지 않는다.** 백엔드는 자연스러운 snake_case로 줘도 되고, 프론트 어댑터
>   (`frontend/web/src/lib/api/chatAdapter.ts`)가 정규화한다. 이 문서가 정의하는 것은 casing이 아니라
>   **"어떤 필드를, 어떤 구조·의미로 주는가"**다. (아래 예시는 camelCase로 표기했지만 snake_case 대응 키도 동일하게 받는다.)
> - 백엔드는 아직 골격 단계라 일부 값이 비어 있을 수 있다. **선택 필드는 없어도 되고**, 비면 해당 UI 영역만 빈 채로
>   "미제공"으로 표시된다. (프론트가 임의로 값을 지어내지 않는다.)
> - 기준 타입: `frontend/web/src/lib/api/types.ts` (`RunResponse` 등).

---

## 현재 연동 방식 (요약)

- 백엔드 데이터 창구는 **`POST /chat` 하나**다. 식단·영양·장보기·파이프라인 결과가 이 응답 하나에 모두 들어온다.
- 현재 백엔드는 LangGraph state를 **snake_case**로 반환하고, 프론트의 `frontend/web/src/lib/api/chatAdapter.ts`가
  프론트 내부 형식으로 변환해 사용한다. (casing 변환도 어댑터가 처리하므로 백엔드는 snake_case 유지해도 된다.)
- **백엔드가 아래 필드들을 채워줄수록** 지금 비어 있는 값들이 화면에 채워진다. 이 문서는 그 목표 **필드 구성**을 정의한다.

---

## 1. 엔드포인트

| 메서드 · 경로 | 용도 | 응답 |
|---|---|---|
| `GET /health` | 생존 확인 | `{"status": "ok"}` |
| `POST /chat` | ⭐ 핵심. 입력 → 전체 결과(식단·영양·장보기·파이프라인) | 아래 3장 형식 |
| `/docs`, `/openapi.json`, `/redoc` | FastAPI 자동 문서 (개발용) | - |

> 쿠팡 장바구니 자동 담기는 **역할 D 의 Chrome 확장(`frontend/extension`)**이 사용자 브라우저에서 직접 처리한다.
> 웹페이지 ↔ 확장은 `postMessage` 브리지로만 통신하며 **백엔드 호출이 없다.** 따라서 백엔드가 만들 엔드포인트도 없다.

---

## 2. 요청 형식 — `POST /chat` (프론트 → 백엔드)

현재 백엔드(`backend/app/main.py`)가 받는 요청 형식:

```jsonc
{
  "message": "냉장고에 두부, 계란, 애호박 있어. 고단백 식단 짜줘",  // 필수, 자연어 한 문장
  "budget_limit": 30000                                            // 선택, int | null (예산, 원)
}
```

| 필드 | 타입 | 필수 | 비고 |
|---|---|---|---|
| `message` | string | ✅ | 재료·목표를 담은 자연어 문장 |
| `budget_limit` | int \| null | ❌ | 예산(원). 없으면 예산 검증 통과 |

> 프론트 입력 폼에는 단백질/칼로리 목표·인원·제외 재료·조리시간·배송 선호 등 구조화 필드가 더 있다(`FridgeMateRequest`).
> 현재는 이를 `message` 한 문장으로 합쳐 보낸다. 향후 백엔드가 구조화 입력을 받게 되면 이 절을 확장한다.

---

## 3. 응답 형식 — `POST /chat` (백엔드 → 프론트) ★ 이 문서의 핵심

아래 모양으로 내려주면 프론트 화면이 그대로 채워진다. (선택 필드는 없어도 됨)

### 3.0 전체 예시

```jsonc
{
  "runId": "run_ab12cd34",
  "mode": "goal",
  "ingredients": ["닭가슴살", "계란", "브로콜리", "두부"],

  "pantry": {
    "items": [
      { "name": "닭가슴살", "category": "단백질",       "freshness": "fresh",  "note": "냉장 보관 양호" },
      { "name": "브로콜리", "category": "채소",         "freshness": "urgent", "expiryLabel": "D-2" },
      { "name": "두부",     "category": "단백질(식물성)","freshness": "soon",   "expiryLabel": "D-1", "amount": "1모" }
    ],
    "priorityUse": ["두부", "브로콜리"],
    "summary": "유통기한이 가까운 두부와 브로콜리를 먼저 사용하는 식단으로 구성했어요."
  },

  "recipes": [
    {
      "id": "rcp_1",
      "title": "닭가슴살 두부 강된장 덮밥",
      "description": "두부와 닭가슴살을 강된장에 볶아 현미밥에 올린 고단백 한 그릇.",
      "cookMinutes": 18,
      "servings": 2,
      "tags": ["고단백", "저탄수"],
      "mainIngredients": ["닭가슴살", "두부", "양파"],
      "citations": [
        { "label": "식품의약품안전처 식품영양성분DB", "sourceId": "mfds-food-db", "url": "https://various.foodsafetykorea.go.kr" }
      ],
      "score": {
        "baseScore": 0.81, "seasonalBonus": 0.06, "trendBonus": 0.04, "finalScore": 0.91,
        "reasons": ["임박 재료(두부) 우선 사용", "고단백 목표 적합"]
      }
    }
    // ... 레시피 여러 개 (3개 이상 권장)
  ],

  "mealPlan": {
    "note": "임박 재료를 앞쪽 일자에 배치했어요.",
    "days": [
      {
        "label": "1일차",
        "entries": [
          { "slot": "아침", "recipeTitle": "브로콜리 계란 스크램블",  "usesPriorityItem": true },
          { "slot": "점심", "recipeTitle": "닭가슴살 두부 강된장 덮밥", "usesPriorityItem": true },
          { "slot": "저녁", "recipeTitle": "닭가슴살 두부 스테이크",   "usesPriorityItem": false }
        ]
      }
      // ... 2일차, 3일차 ...
    ]
  },

  "nutrition": {
    "protein":  { "current": 124,  "target": 120,  "unit": "g" },
    "calories": { "current": 1660, "target": 1700, "unit": "kcal" },
    "carbs":    { "current": 132,  "target": 150,  "unit": "g" },
    "fat":      { "current": 48,   "target": 55,   "unit": "g" },
    "passed": true,
    "message": "단백질·칼로리 목표를 충족했어요.",
    "warnings": []
  },

  "shopping": {
    "items": [
      {
        "name": "현미", "quantity": "1kg", "priceKrw": 6900,
        "reason": "저탄수 목표에 맞춘 잡곡 베이스",
        "delivery": "내일 도착(로켓배송)",
        "isAlternative": false,
        "productUrl": "https://www.coupang.com/vp/products/1221588314",
        "score": { "shoppingScore": 88, "priceScore": 90, "reasons": ["영양 적합도 높음"] }
      },
      {
        "name": "방울토마토", "quantity": "500g", "priceKrw": 5500,
        "reason": "파프리카 대체", "isAlternative": true, "alternativeFor": "파프리카"
      }
      // ... 부족 재료 여러 개 ...
    ],
    "estimatedCostKrw": 23580,
    "budgetKrw": 100000,
    "withinBudget": true,
    "coupangSearchUrl": "https://www.coupang.com/np/search?q=현미%20방울토마토",
    "coupangCartUrl": null
  },

  "pipeline": [
    { "id": "pantry",   "order": 1, "name": "Pantry Agent",   "status": "completed", "message": "재료 분석 완료", "logs": ["재료 4종 정규화"] },
    { "id": "recipe",   "order": 2, "name": "Recipe Agent",   "status": "completed", "message": "레시피 후보 검색 완료" },
    { "id": "meal",     "order": 3, "name": "Meal Agent",     "status": "running",   "message": "영양 목표 검증 중" },
    { "id": "shopping", "order": 4, "name": "Shopping Agent", "status": "pending",   "message": "부족 재료 계산 대기" },
    { "id": "executor", "order": 5, "name": "Executor Agent", "status": "pending",   "message": "쿠팡 자동 담기 대기" }
  ],

  "warnings": [],
  "notice": null
}
```

### 3.1 최상위 (`RunResponse`)

| 필드 | 타입 | 필수 | 설명 | 담당(제안) |
|---|---|---|---|---|
| `runId` | string | ✅ | 실행 식별자(추적용) | 오케스트레이터 |
| `mode` | string | ✅ | `today`\|`weekend`\|`meal_prep`\|`goal` (요청 echo) | echo |
| `ingredients` | string[] | ✅ | 입력 재료명 목록 | echo/파서 |
| `pantry` | object | ✅ | 3.2 | 파서 |
| `recipes` | object[] | ✅ | 3.3 | RAG |
| `mealPlan` | object | ✅ | 3.4 | Meal |
| `nutrition` | object | ✅ | 3.5 | 영양 Tool + Judge |
| `shopping` | object | ✅ | 3.6 | 부족재료/가격 + 상품점수 |
| `pipeline` | object[] | ✅ | 3.7 (5개 고정) | 오케스트레이터 |
| `warnings` | string[] | ✅ | 경고 문구(빈 배열 가능) | 오케스트레이터 |
| `notice` | string | ❌ | 안내 문구 | - |

### 3.2 `pantry` (PantryAnalysis)

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| `items` | PantryItem[] | ✅ | 재료 목록 |
| `priorityUse` | string[] | ✅ | 우선 사용(임박) 재료 이름들 |
| `summary` | string | ✅ | 요약 한 줄 |

**PantryItem**: `name`✅, `category`✅(단백질/채소/가공…), `freshness`✅(`fresh`\|`soon`\|`urgent`) / 선택: `expiryLabel`("D-1"), `note`, `amount`("1모"), `expirationDate`("2025-05-18"), `storageType`("냉장 보관")

### 3.3 `recipes` (Recipe[])

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| `id` | string | ✅ | 레시피 식별자 |
| `title` | string | ✅ | 이름 |
| `description` | string | ✅ | 설명 |
| `tags` | string[] | ✅ | 태그(없으면 빈 배열) |
| `mainIngredients` | string[] | ✅ | 주재료명 |
| `citations` | Citation[] | ✅ | 출처(없으면 빈 배열) |
| `cookMinutes` | number | ❌ | 조리 시간(분) |
| `servings` | number | ❌ | 인분 |
| `score` | ScoreInfo | ❌ | 레시피 점수(3.8) |

**Citation**: `label`✅, `sourceId`✅ / `url`❌

### 3.4 `mealPlan` (MealPlan)

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| `days` | MealPlanDay[] | ✅ | 일자별 식단 |
| `note` | string | ❌ | 식단 메모 |

- **MealPlanDay**: `label`✅("1일차"), `entries`✅
- **MealPlanEntry**: `slot`✅(아침/점심/저녁), `recipeTitle`✅ / `usesPriorityItem`❌(임박 재료 사용 여부)

### 3.5 `nutrition` (NutritionVerification)

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| `protein` | NutrientMetric | ✅ | 단백질 |
| `calories` | NutrientMetric | ✅ | 칼로리 |
| `passed` | boolean | ✅ | 영양 목표 충족 여부 |
| `message` | string | ✅ | PASS/보완 안내 문구 |
| `carbs` | NutrientMetric | ❌ | 탄수화물 |
| `fat` | NutrientMetric | ❌ | 지방 |
| `warnings` | string[] | ❌ | 영양 경고 |
| `notProvided` | string[] | ❌ | 미제공 항목명(표시용, 예: "탄수화물") |

**NutrientMetric**: `current`✅, `target`✅, `unit`✅ (예: `{ "current": 124, "target": 120, "unit": "g" }`)

### 3.6 `shopping` (ShoppingList)

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| `items` | ShoppingItem[] | ✅ | 부족 재료 목록 |
| `estimatedCostKrw` | number | ✅ | 예상 총액(원) |
| `withinBudget` | boolean | ✅ | 예산 이내 여부 |
| `coupangSearchUrl` | string | ✅ | 쿠팡 검색 URL |
| `budgetKrw` | number | ❌ | 예산(원) |
| `coupangCartUrl` | string | ❌ | 장바구니 URL |

**ShoppingItem**: `name`✅, `quantity`✅("1kg", 표시용 문자열), `priceKrw`✅ / 선택: `reason`, `delivery`("내일 도착(로켓배송)"), `isAlternative`, `alternativeFor`, `productUrl`(쿠팡 상품 상세 URL), `addMode`("direct"\|"adjust"), `purchaseCount`(담을 정수 개수), `score`(ScoreInfo)

> `productUrl`(개별 상품 페이지 URL)이 있으면 Chrome 확장이 자동 담기를 시도하고, 없으면 그 품목은 `skipped`.

#### 3.6.1 쿠팡 자동 담기(확장) 실행용 필드 — `direct` / `adjust`

확장이 상품을 담는 방식은 두 가지이며, **"이 URL이 필요 수량을 이미 품고 있는가"는 상품 메타데이터라 프론트가 판단할 수 없다.** 그래서 URL을 고른 백엔드(상품 검색/부족재료 해소 단계)가 방식을 알려준다.

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| `productUrl` | string | (담기 대상) | 쿠팡 상품 페이지 URL. 없으면 그 품목은 `skipped` |
| `addMode` | string | ❌ | `direct` \| `adjust`. 없으면 프론트가 `purchaseCount`로 추정(아래) |
| `purchaseCount` | int | ❌ | 담을 **정수 개수**. `adjust` 시 페이지 수량 스테퍼를 이 값으로 맞춘다. 없으면 1 |

- **`direct`**: 수량/옵션이 URL(`itemId`·`vendorItemId`)에 이미 박혀 있어 그대로 담으면 되는 경우. (예: 계란 "30구 2판" 옵션 URL)
- **`adjust`**: 기본 상품 페이지라, 확장이 **수량 스테퍼를 `purchaseCount`로 맞춘 뒤** 담아야 하는 경우.

> 같은 상품이라도 수량이 별도 옵션(`itemId`)으로 존재하는지 여부는 상품 메타데이터다.
> 따라서 `addMode`는 **백엔드가 지정**하는 것이 정확하다.

**`addMode` 미제공 시 프론트 fallback(차선):** `purchaseCount <= 1` → `direct`, `> 1` → `adjust`.
단, 수량이 URL에 박힌 상품을 `adjust`로 오인할 수 있어 완벽하지 않으므로 **가능하면 `addMode` 명시를 권장**한다.

> 프론트 매핑: 이 값들은 `chatAdapter`에서 `CartExecuteItem.{productUrl, quantity, addMode}`로 전달되어 확장이 사용한다(`frontend/extension/background.js`).

### 3.7 `pipeline` (AgentPipelineItem[]) — 5개 고정

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| `id` | string | ✅ | `pantry`\|`recipe`\|`meal`\|`shopping`\|`executor` |
| `order` | number | ✅ | 1~5 |
| `name` | string | ✅ | 표시 이름 |
| `status` | string | ✅ | `completed`\|`running`\|`pending`\|`failed` |
| `message` | string | ✅ | 현재 상태 문구 |
| `logs` | string[] | ❌ | 단계별 로그 |

> `executor` 단계는 **실제 쿠팡 담기(Chrome 확장)** 를 의미한다. 분석 파이프라인은 `shopping`까지이고,
> `executor` 완료는 백엔드가 아니라 **사용자가 "장바구니 담기 실행"을 눌러 확장이 성공했을 때** 프론트가 표시한다.
> 따라서 백엔드는 `executor`를 `pending`으로 둬도 된다.

### 3.8 `ScoreInfo` (전부 선택, 표시 전용)

- 레시피용: `baseScore`, `seasonalBonus`, `trendBonus`, `finalScore`
- 상품용: `shoppingScore`, `deliveryScore`, `priceScore`, `freshnessScore`, `nutritionFitScore`
- 공통: `reasons`(string[])

> **점수·추론 값은 프론트에서 계산하지 않는다.** 백엔드가 주면 표시, 없으면 그 칸만 비운다.

---

## 4. 최소 구현(MVP) vs 풀

**MVP — 이것만 와도 화면이 동작한다:**

- `runId`, `mode`, `ingredients`
- `pantry.{items, priorityUse, summary}`
- `recipes[].{id, title, description, tags, mainIngredients, citations}`
- `mealPlan.days[].entries[]`
- `nutrition.{protein, calories, passed, message}`
- `shopping.{items[].{name, quantity, priceKrw}, estimatedCostKrw, withinBudget, coupangSearchUrl}`
- `pipeline[]` (5개 상태)

**그 다음(풀):** `score`(레시피/상품 점수), `nutrition.{carbs, fat, warnings}`, `recipes[].{cookMinutes, servings}`,
`shopping.items[].{delivery, isAlternative, productUrl}`, `warnings`, `notice`.

---

## 5. 규칙

- **casing은 자유** — snake_case/camelCase 무관. 프론트 어댑터(`chatAdapter.ts`)가 정규화한다. 중요한 건 **필드 구성·구조·의미**다.
- **선택 필드 누락 OK** — 해당 UI 영역만 비고 나머지는 정상 표시된다.
- **없는 값을 지어내지 않는다** — 프론트는 빈 값을 "미제공"으로 표시한다.
- `coupangSearchUrl`은 백엔드가 주거나, 없으면 프론트가 재료명으로 생성한다.

---

## 6. 운영 메모

### 6.1 mock / real 전환 (`frontend/web/.env.local`)

| 변수 | 기본 | 의미 |
|---|---|---|
| `NEXT_PUBLIC_USE_MOCK_API` | `true` | `true`=mock(백엔드 불필요), `false`=실제 `/chat` 호출 |
| `NEXT_PUBLIC_API_BASE_URL` | `http://localhost:8000` | 백엔드 주소 |
| `NEXT_PUBLIC_API_FALLBACK_TO_MOCK` | `true` | real 실패 시 mock 으로 대체 + 안내 |

real 전환: 백엔드 기동 → `NEXT_PUBLIC_USE_MOCK_API=false` → 끝. UI 컴포넌트 수정 없음.

### 6.2 CORS (백엔드에 추가 필요)

브라우저에서 `localhost:3000 → localhost:8000/chat` 직접 호출이 차단되지 않도록 백엔드에 한 줄 추가가 필요하다:

```python
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)
```
