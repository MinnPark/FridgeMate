# apps/web — FridgeMate AI 프론트엔드

Next.js 14 (App Router, TypeScript, Tailwind) 기반 대시보드. 역할 D 핵심 산출물.

## 실행
```bash
npm install
cp .env.local.example .env.local   # 기본 mock 모드
npm run dev                        # http://localhost:3000
```
mock 모드(기본)는 백엔드 없이 동작합니다. real 연동은 루트 README의 환경변수 표 참고.

## 스크립트
| 명령 | 설명 |
|---|---|
| `npm run dev` | 개발 서버 |
| `npm run build` | 프로덕션 빌드 |
| `npm run start` | 빌드 결과 실행 |
| `npm run lint` | ESLint |
| `npm run typecheck` | `tsc --noEmit` |

> dev 서버 구동 중에 `npm run build` 를 동시에 돌리면 `.next` 캐시가 충돌할 수 있습니다.
> 빌드 시엔 dev 서버를 끄거나, 평소엔 typecheck/lint 로 검증하세요.

## 폴더 구조
```txt
src/
├─ app/
│  ├─ page.tsx          # 한 페이지 대시보드 (좌: 메인 / 우: Agent Pipeline)
│  ├─ layout.tsx  globals.css
├─ components/
│  ├─ Header, InputPanel, ConditionBar          # 입력 영역
│  ├─ PantryCard, NutritionCard, RecipesCard, MealPlanCard   # 요약 카드(+Modal 상세)
│  ├─ CartExecutionCard                          # 부족 재료 + 쿠팡 실행 통합
│  ├─ AgentPipelinePanel                         # 우측 5-Agent 패널
│  ├─ Modal, IngredientDetailModal, ScoreBadge   # 공용/보조
└─ lib/api/
   ├─ types.ts          # 요청/응답 타입 (apps/api 스키마와 1:1)
   ├─ mock.ts           # 프론트 mock 데이터
   ├─ client.ts         # ★ 어댑터: runPipeline / createCart (mock·real 분기)
   ├─ coupang.ts        # 쿠팡 링크 유틸
   └─ extensionBridge.ts # Chrome 확장 ↔ 페이지 메시지 브리지
```

## 핵심 설계
- 컴포넌트는 `runPipeline()` / `createCart()` 만 호출 — mock/real 전환은 환경변수 한 줄.
- 상세 정보는 **모달 오버레이**(`Modal`)로 표시 — 페이지를 세로로 늘리지 않음.
- 쿠팡 자동 담기는 `extensionBridge` 를 통해 **Chrome 확장**이 실행(결제 없음).
