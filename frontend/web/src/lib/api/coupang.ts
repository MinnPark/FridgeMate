// FridgeMate AI - 쿠팡 실행부(Executor) 링크 유틸 (역할 D)
//
// 실제 자동 담기는 Chrome 확장(extensionBridge)이 수행한다.
// 여기서는 사용자가 "직접 열어서 확인"하는 링크(검색/상품/장바구니 페이지)만 다룬다.
// 실제 로그인/결제/자동 구매는 어떤 경우에도 수행하지 않는다.

import type { CartResponse } from "./types";

const COUPANG_CART_PAGE = "https://cart.coupang.com/cartView.pa";

function openUrl(url?: string | null): boolean {
  if (typeof window === "undefined" || !url) return false;
  window.open(url, "_blank", "noopener,noreferrer");
  return true;
}

/** 쿠팡 검색 결과 페이지를 새 탭으로 연다. */
export function openCoupangSearch(searchUrl?: string | null): boolean {
  return openUrl(searchUrl);
}

/** 장바구니 URL 우선, 없으면 검색 URL 로 폴백해 새 탭으로 연다. */
export function openCoupangCart(cart: CartResponse): boolean {
  return openUrl(cart.coupangCartUrl || cart.coupangSearchUrl);
}

/** 쿠팡 장바구니 페이지를 연다(자동 담기 후 사용자가 직접 확인용). */
export function openCoupangCartPage(): boolean {
  return openUrl(COUPANG_CART_PAGE);
}

/** 화면 표시용 금액 포맷 (예: 6900 → "₩6,900"). */
export function formatKRW(value: number): string {
  return `₩${value.toLocaleString("ko-KR")}`;
}
