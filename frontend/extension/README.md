# FridgeMate Cart Helper (Chrome 확장 프로그램)

FridgeMate AI 장보기 리스트를 **사용자의 실제 Chrome** 에서 쿠팡 장바구니에
담아주는 도우미입니다. Playwright 와 달리 별도 자동화 브라우저를 띄우지 않으므로
쿠팡 봇 탐지(Akamai)에 막히지 않습니다.

- 담기까지만 수행하고 **결제/구매는 하지 않습니다.**
- 쿠팡 로그인은 사용자가 평소처럼 직접 합니다. **계정 정보를 다루지 않습니다.**
- 사용자가 화면에서 "자동 담기 실행 → 확인하고 실행" 을 누를 때만 동작합니다.

## 설치 (개발자 모드 · 압축 해제된 확장)

1. Chrome 주소창에 `chrome://extensions` 입력.
2. 오른쪽 위 **개발자 모드** 켜기.
3. **압축해제된 확장 프로그램을 로드합니다** 클릭 → 이 폴더(`frontend/extension`) 선택.
4. 확장이 목록에 뜨면 완료. (FridgeMate 페이지를 새로고침)

## 사용

1. 쿠팡에 평소 쓰는 Chrome 으로 **로그인**해 둡니다.
2. FridgeMate(http://localhost:3000)에서 **자동 담기 실행 → 확인하고 실행**.
3. 상품 URL 이 있는 품목이 백그라운드 탭으로 순차로 열리고 "장바구니 담기"가 눌립니다.
4. 화면에 품목별 성공/실패/건너뜀 결과가 표시됩니다.

## 동작 방식

```
FridgeMate 페이지 ──postMessage──▶ content-fridgemate.js ──▶ background.js
                                                              │ (탭 생성 + executeScript)
                                                              ▼
                                                      쿠팡 상품 페이지에서
                                                      '장바구니 담기' 클릭
```

## 주의

- 쿠팡 DOM 변경 시 버튼 selector 가 안 맞을 수 있습니다 (`background.js` 의
  `clickAddToCartInPage` 에서 텍스트 기준으로 찾습니다).
- 상품 URL 이 없는 품목은 `skipped` 처리됩니다.
- 결제/구매(`바로구매`, `구매하기`, `결제`, `주문`) 버튼은 클릭하지 않습니다.
