# Frontend ↔ Backend 통합 가이드 (역할 D)

이 repo의 `frontend/`(Next.js, 역할 D)와 `backend/`(LangGraph, `POST /chat`)를
연결하는 방법. **백엔드는 수정하지 않고**, 프론트의 어댑터가 차이를 흡수한다.

## 연결 구조

```
frontend/web (Next.js, :3000)  ──HTTP──▶  backend (FastAPI/LangGraph, :8000)
   runPipeline()                          POST /chat  { message, budget_limit }
        │  client.ts                              │
        │  ├─ mapRequestToChat()  : 구조화 입력 → message/budget_limit
        ▼  └─ mapChatToRunResponse(): /chat state(snake) → RunResponse(camel)
   UI 컴포넌트 (수정 없음)
```

핵심 파일: `frontend/web/src/lib/api/chatAdapter.ts` (요청/응답 매퍼),
`frontend/web/src/lib/api/client.ts` (real 모드에서 `/chat` 호출).

## 실행 방법

```bash
# 1) 백엔드
cd backend
python -m venv .venv && .venv/Scripts/activate   # (mac/linux: source .venv/bin/activate)
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000

# 2) 프론트
cd frontend/web
npm install
cp .env.local.example .env.local
#   .env.local 에서 real 모드로:
#     NEXT_PUBLIC_USE_MOCK_API=false
#     NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
npm run dev   # http://localhost:3000
```

> mock 모드(`NEXT_PUBLIC_USE_MOCK_API=true`, 기본)는 백엔드 없이도 전체 화면이 동작.

## 매퍼가 변환하는 것

| 백엔드 `/chat` (snake) | → 프론트 `RunResponse` (camel) |
|---|---|
| `pantry_items[]` (expiry_priority) | `pantry.items[]` (freshness, amount) + `priorityUse` |
| `selected_recipes[]` (중복 가능) | `recipes[]` (id로 중복 제거) |
| `meal_plan.days[].meals[]` | `mealPlan.days[].entries[]` (slot 한글화) |
| `logs[].nutrition_verified.result` | `nutrition.protein/calories/passed` |
| `cart_items[]` (price, deeplink) | `shopping.items[]` (priceKrw) + `coupangSearchUrl` |
| `logs` / 노드 존재 | `pipeline[]` 5개 최소 상태 |

## 백엔드 미제공 → "미제공/연동 대기"로 표시 (가짜로 안 채움)

- 레시피 `cookMinutes`, `servings`(사용자값 사용), `tags`, 점수 → 비움
- 영양 `carbs`/`fat`, 칼로리 목표 → `nutrition.notProvided` 에 명시
- 상품 `productUrl`(백엔드는 검색 deeplink만), 상품 점수, 배송 → 비움
  → Chrome 확장 자동 담기는 `productUrl` 이 없으면 `skipped`
- `pipeline.executor` → `pending` ("백엔드 미연동")
- 응답 상단 `notice` 로 "변환 표시 중 + 일부 미제공" 안내

## CORS (브라우저 연동 시 필요)

백엔드 `main.py` 에 CORS 가 없어, 브라우저에서 `:3000 → :8000` 호출은 차단된다.
백엔드 담당자가 아래 최소 미들웨어를 추가하면 된다(프론트는 변경 불필요):

```python
from fastapi.middleware.cors import CORSMiddleware
app.add_middleware(
    CORSMiddleware, allow_origins=["http://localhost:3000"],
    allow_methods=["*"], allow_headers=["*"],
)
```

## 팀원과 맞출 API 스키마 (다음 협의 사항)

현재 `/chat` 은 LangGraph state 를 통째로 반환한다. 합의가 필요한 부분:
1. **영양 검증 결과**를 state 최상위로(`nutrition`: total/goal/passed + carbs/fat/calorie target)
2. **Agent Pipeline 상태**(completed/running/pending)를 명시적으로
3. **상품 URL**(`product_url`) — 자동 담기 정확도용 (현재는 검색 deeplink만)
4. (선택) `/api/run` 같은 정형 엔드포인트로 정리하면 매퍼 없이 직결 가능
   → 상세 계약 예시: 프론트의 `chatAdapter.ts` 주석 및 타입 참고
