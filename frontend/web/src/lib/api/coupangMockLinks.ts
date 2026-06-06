// 쿠팡 장바구니 담기 — mock 링크 (역할 D)
//
// 재료 URL 을 내려주는 백엔드가 개발 중이라, 그 전까지 확장의 두 담기 경로를
// 실제 쿠팡에서 검증하기 위한 임시 mock 데이터.
//   - addMode "direct" : itemId/vendorItemId 에 옵션·수량이 박혀 있어 URL 그대로 담김.
//   - addMode "adjust" : 상품페이지에서 수량을 quantity 로 맞춘 뒤 담아야 하는 상품.
// 백엔드 연동 시 이 배열을 실제 응답 매핑으로 교체하면 된다.
//
// ⚠️ ingredient 명은 확인된 것(계란) 외에는 placeholder — 실제 상품명으로 교체 가능.

import type { CartExecuteItem } from "./types";

export const MOCK_CART_LINKS: CartExecuteItem[] = [
  // ── ① URL대로 담기 (direct) ─────────────────────────────
  {
    ingredient: "계란 30구 (2개)",
    addMode: "direct",
    quantity: 2,
    productUrl:
      "https://www.coupang.com/vp/products/7464735307?itemId=19465005945&vendorItemId=78233728695&sourceType=srp_product_ads&clickEventId=5700dc70-619d-11f1-90fb-39fc0dbdd0ee&korePlacement=15&koreSubPlacement=1&clickEventId=5700dc70-619d-11f1-90fb-39fc0dbdd0ee&korePlacement=15&koreSubPlacement=1",
  },
  {
    ingredient: "테스트 상품 B",
    addMode: "direct",
    quantity: 1,
    productUrl:
      "https://www.coupang.com/vp/products/130180913?itemId=383114455&vendorItemId=3930090438&sourceType=CATEGORY&categoryId=434952&traceId=mq2aqua6",
  },
  {
    ingredient: "테스트 상품 C",
    addMode: "direct",
    quantity: 1,
    productUrl:
      "https://www.coupang.com/vp/products/1301524802?itemId=24477966055&vendorItemId=91491430900&sourceType=CATEGORY&categoryId=503584&traceId=mq2ar6es",
  },

  // ── ② 갯수 지정 (adjust) ────────────────────────────────
  {
    ingredient: "테스트 상품 D",
    addMode: "adjust",
    quantity: 6,
    productUrl:
      "https://www.coupang.com/vp/products/8481145163?itemId=22081543335&vendorItemId=3009605778&pickType=COU_PICK&sourceType=srp_product_ads&clickEventId=b3bad910-619e-11f1-88c6-73bce1f98d4a&korePlacement=15&koreSubPlacement=1&clickEventId=b3bad910-619e-11f1-88c6-73bce1f98d4a&korePlacement=15&koreSubPlacement=1&traceId=mq2armvp",
  },
  {
    ingredient: "테스트 상품 E",
    addMode: "adjust",
    quantity: 3,
    productUrl:
      "https://www.coupang.com/vp/products/2233944921?itemId=5617626770&vendorItemId=72916817045&sourceType=CATEGORY&categoryId=420108&traceId=mq2as9sf",
  },
];
