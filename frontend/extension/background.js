// FridgeMate Cart Helper - background service worker (MV3)
//
// FridgeMate 페이지에서 받은 장보기 리스트를, 사용자의 실제 Chrome 으로
// 쿠팡 상품 탭을 순차로 열고 "장바구니 담기"까지만 누른다.
// - 담기 성공 시 해당 탭을 닫는다.
// - 품목마다 진행 상황을 페이지로 전송한다(진행률 표시용).
// - 결제/구매 버튼은 절대 누르지 않는다.

const NAV_TIMEOUT_MS = 20000;
const CLICK_ATTEMPTS = 10; // 버튼이 렌더될 때까지 짧게 재시도
const CLICK_GAP_MS = 350;
const SETTLE_MS = 1500; // 클릭 후 담기 요청이 서버에 반영될 시간(탭을 너무 빨리 닫지 않도록)
const CART_PAGE_URL = "https://cart.coupang.com/";

// 페이지 컨텍스트에서 실행: 장바구니 담기 버튼만 찾아 클릭.
function clickAddToCartInPage() {
  const FORBIDDEN = ["바로구매", "구매하기", "결제", "주문"];
  const els = Array.from(
    document.querySelectorAll("button, a, input[type=button], input[type=submit]")
  );
  const btn = els.find((el) => {
    // 헤더의 '장바구니' 네비게이션 링크(담기 아님)는 제외 → cart.coupang.com 으로 가는 링크 배제.
    const href = (el.getAttribute && el.getAttribute("href")) || "";
    if (/cart\.coupang\.com/.test(href)) return false;
    const t = (el.innerText || el.value || "").trim();
    if (!t) return false;
    if (FORBIDDEN.some((f) => t.includes(f))) return false;
    // '장바구니' 단독(헤더 네비)으로는 매칭하지 않고, 실제 담기 버튼 문구만 매칭.
    return t.includes("장바구니 담기");
  });
  if (!btn) return { status: "notfound" };
  try {
    btn.scrollIntoView({ block: "center" });
    btn.click();
    return { status: "success" };
  } catch (e) {
    return { status: "error" };
  }
}

function delay(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

function waitForTabComplete(tabId, timeout = NAV_TIMEOUT_MS) {
  return new Promise((resolve, reject) => {
    const start = Date.now();
    const tick = () => {
      chrome.tabs.get(tabId, (tab) => {
        if (chrome.runtime.lastError) return reject(chrome.runtime.lastError);
        if (tab && tab.status === "complete") return resolve();
        if (Date.now() - start > timeout) return resolve(); // 타임아웃이어도 클릭 시도
        setTimeout(tick, 300);
      });
    };
    tick();
  });
}

// 버튼이 나타나는 즉시 클릭(고정 대기 없이 빠르게).
async function clickWithRetry(tabId) {
  for (let i = 0; i < CLICK_ATTEMPTS; i++) {
    try {
      const injected = await chrome.scripting.executeScript({
        target: { tabId },
        func: clickAddToCartInPage,
      });
      const r = injected && injected[0] && injected[0].result;
      if (r && r.status === "success") return { ok: true };
    } catch (e) {
      // 페이지가 아직 로딩 중일 수 있음 → 재시도
    }
    await delay(CLICK_GAP_MS);
  }
  return { ok: false };
}

async function processItem(item) {
  const name = item.ingredient;
  const url = item.productUrl;
  if (!url) {
    return { itemName: name, status: "skipped", message: "상품 URL이 없어 건너뛰었습니다." };
  }
  let tab;
  try {
    tab = await chrome.tabs.create({ url, active: false });
    await waitForTabComplete(tab.id);
    const res = await clickWithRetry(tab.id);
    if (res.ok) {
      // 클릭 직후 바로 닫으면 담기 요청(비동기)이 취소될 수 있어, 잠시 대기 후 닫는다.
      await delay(SETTLE_MS);
      try {
        await chrome.tabs.remove(tab.id); // 담았으면 탭 닫기
      } catch (e) {}
      return {
        itemName: name,
        productUrl: url,
        status: "success",
        message: "장바구니 담기 완료. (결제는 진행하지 않음)",
      };
    }
    return {
      itemName: name,
      productUrl: url,
      status: "failed",
      message: "장바구니 버튼을 찾지 못했습니다. 로그인 또는 상품 옵션 선택이 필요할 수 있어요.",
    };
  } catch (e) {
    return {
      itemName: name,
      productUrl: url,
      status: "failed",
      message: "상품 페이지 처리에 실패했습니다: " + (e && e.message ? e.message : e),
    };
  }
}

function sendProgress(senderTabId, reqId, payload) {
  try {
    chrome.tabs.sendMessage(senderTabId, {
      type: "FRIDGEMATE_EXEC_PROGRESS",
      reqId,
      ...payload,
    });
  } catch (e) {}
}

async function executeCart(items, senderTabId, reqId) {
  const total = items.length;
  const results = [];

  for (let i = 0; i < total; i++) {
    sendProgress(senderTabId, reqId, {
      phase: "item-start",
      index: i,
      total,
      itemName: items[i].ingredient,
    });
    const r = await processItem(items[i]);
    results.push(r);
    sendProgress(senderTabId, reqId, {
      phase: "item-done",
      index: i,
      total,
      done: results.length,
      result: r,
    });
  }

  const success = results.filter((r) => r.status === "success").length;
  const failed = results.filter((r) => r.status === "failed").length;
  const skipped = results.filter((r) => r.status === "skipped").length;
  const status =
    success === 0 && failed > 0
      ? "failed"
      : failed > 0 || skipped > 0
        ? "partial_failed"
        : "completed";

  // 담은 게 있으면 마지막에 장바구니 페이지를 활성 탭으로 연다(결제는 하지 않음).
  let cartOpened = false;
  if (success > 0) {
    try {
      await chrome.tabs.create({ url: CART_PAGE_URL, active: true });
      cartOpened = true;
    } catch (e) {}
  }

  const response = {
    executionMode: "extension",
    status,
    results,
    message:
      `담기 완료 ${success} · 실패 ${failed} · 건너뜀 ${skipped}. ` +
      (cartOpened
        ? "장바구니 페이지를 열었어요. 결제는 진행하지 않았습니다."
        : "결제는 진행하지 않았습니다."),
  };
  chrome.tabs.sendMessage(senderTabId, { type: "FRIDGEMATE_EXEC_RESULT", reqId, response });
}

chrome.runtime.onMessage.addListener((msg, sender) => {
  if (msg && msg.type === "FRIDGEMATE_EXEC_CART" && sender.tab) {
    executeCart(msg.items || [], sender.tab.id, msg.reqId);
  }
  return false;
});
