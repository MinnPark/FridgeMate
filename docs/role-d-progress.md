# 역할 D (Execution / UI) 진행 상황

## 산출물 (`frontend/`)
- Next.js 14 한 페이지 대시보드: 입력 → Pantry/영양/레시피/식단 요약 카드 → 부족 재료·쿠팡 실행 통합 카드 → 우측 Agent Pipeline
- 상세 정보는 **모달 오버레이**로(페이지 세로 안 늘어남)
- 재료 입력: Enter → 용량/유통기한 입력 팝업 → Pantry 반영
- 쿠팡 자동 담기: **Chrome 확장**(`frontend/extension` — 결제·계정저장 없음)
- API 어댑터: mock ↔ real 분기 + 백엔드 `/chat` 변환 매퍼

## 백엔드(`backend/`) 연동
- 방식: **백엔드 무수정**, 프론트 `client.ts`/`chatAdapter.ts` 가 `/chat` 응답을 변환
- 상세: [docs/frontend-integration.md](frontend-integration.md)

## 현재 실제 동작 vs 미제공
- **동작**: 입력 → /chat → 식단·레시피·부족재료·영양검증(단백질) 표시, mock 모드 데모
- **미제공(백엔드 연동 대기)**: 조리시간·태그·상품점수·상품URL·탄수/지방·칼로리목표·파이프라인 상태 → 화면에 "미제공"으로 표기(가짜값 없음)

## 다음 협의 (API 스키마)
영양 검증 결과 / Agent Pipeline 상태 / 상품 URL 을 백엔드 응답에 포함하는 합의가 되면,
프론트는 매퍼만 줄이거나 제거하면 됨. (`chatAdapter.ts` 참고)

> 참고: 프론트 단독 문서는 [frontend/web/README.md](../frontend/web/README.md),
> 확장 설치법은 [frontend/extension/README.md](../frontend/extension/README.md).
