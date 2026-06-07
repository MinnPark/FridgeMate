// FridgeMate AI - Chrome 확장 프로그램 다리(bridge) (역할 D)
//
// 자동 담기 실행을 (Playwright 백엔드가 아니라) 사용자의 실제 Chrome 에 설치된
// 확장 프로그램에 위임한다. 페이지는 window.postMessage 로만 통신한다.

import type {
  CartAddResult,
  CartExecuteItem,
  CartExecuteResponse,
  CoupangProductSearchResult,
} from "./types";

/** 담기 진행 상황(품목 시작/완료). 확장 → 페이지로 실시간 전달된다. */
export interface ExecProgress {
  phase: "item-start" | "item-done";
  index: number;
  total: number;
  itemName?: string;
  done?: number;
  result?: CartAddResult;
}

export interface SearchProgress {
  phase: "search-start" | "search-done";
  index: number;
  total: number;
  itemName?: string;
  done?: number;
  result?: CoupangProductSearchResult;
}

/** 확장 프로그램에 살아있는지 핑을 보낸다(응답은 onExtensionReady 로 받음). */
export function pingExtension(): void {
  if (typeof window !== "undefined") {
    window.postMessage({ type: "FRIDGEMATE_PING" }, "*");
  }
}

/** 확장 프로그램 준비(설치/활성) 신호를 구독. 해제 함수를 반환. */
export function onExtensionReady(cb: () => void): () => void {
  if (typeof window === "undefined") return () => {};
  const handler = (e: MessageEvent) => {
    if (e.source === window && e.data?.type === "FRIDGEMATE_EXT_READY") cb();
  };
  window.addEventListener("message", handler);
  return () => window.removeEventListener("message", handler);
}

/** 확장 프로그램을 통해 장바구니 담기를 실행하고 결과를 받는다.
 *  onProgress 가 있으면 품목별 진행 상황을 실시간으로 전달한다. */
export function executeViaExtension(
  items: CartExecuteItem[],
  onProgress?: (p: ExecProgress) => void,
): Promise<CartExecuteResponse> {
  return new Promise((resolve, reject) => {
    if (typeof window === "undefined") {
      reject(new Error("브라우저 환경이 아닙니다."));
      return;
    }
    const reqId = Math.random().toString(16).slice(2);
    const handler = (e: MessageEvent) => {
      if (e.source !== window || !e.data || e.data.reqId !== reqId) return;
      if (e.data.type === "FRIDGEMATE_EXEC_PROGRESS") {
        onProgress?.(e.data as ExecProgress);
      } else if (e.data.type === "FRIDGEMATE_EXEC_RESULT") {
        cleanup();
        resolve(e.data.response as CartExecuteResponse);
      }
    };
    const timer = setTimeout(() => {
      cleanup();
      reject(
        new Error(
          "확장 프로그램이 응답하지 않았어요. 설치/활성화 상태와 쿠팡 로그인을 확인해 주세요.",
        ),
      );
    }, 180000);
    function cleanup() {
      window.removeEventListener("message", handler);
      clearTimeout(timer);
    }
    window.addEventListener("message", handler);
    window.postMessage({ type: "FRIDGEMATE_EXEC_CART", reqId, items }, "*");
  });
}

/** 쿠팡 검색 결과를 확장에서 읽어 상품 후보와 자동 선택 결과를 받는다. */
export function searchProductsViaExtension(
  items: Array<{ ingredient: string; quantityText?: string }>,
  onProgress?: (p: SearchProgress) => void,
): Promise<CoupangProductSearchResult[]> {
  return new Promise((resolve, reject) => {
    if (typeof window === "undefined") {
      reject(new Error("브라우저 환경이 아닙니다."));
      return;
    }
    const reqId = Math.random().toString(16).slice(2);
    const handler = (e: MessageEvent) => {
      if (e.source !== window || !e.data || e.data.reqId !== reqId) return;
      if (e.data.type === "FRIDGEMATE_SEARCH_PROGRESS") {
        onProgress?.(e.data as SearchProgress);
      } else if (e.data.type === "FRIDGEMATE_SEARCH_RESULT") {
        cleanup();
        resolve((e.data.response?.results || []) as CoupangProductSearchResult[]);
      }
    };
    const timer = setTimeout(() => {
      cleanup();
      reject(new Error("쿠팡 상품 검색 시간이 초과되었습니다."));
    }, 120000);
    function cleanup() {
      window.removeEventListener("message", handler);
      clearTimeout(timer);
    }
    window.addEventListener("message", handler);
    window.postMessage({ type: "FRIDGEMATE_SEARCH_PRODUCTS", reqId, items }, "*");
  });
}
