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
const SETTLE_MS = 1000; // 클릭 후 담기 요청이 서버에 반영될 시간(탭을 너무 빨리 닫지 않도록)
const QTY_SETTLE_MS = 1500; // 수량 변경 후 쿠팡이 옵션/가격 재계산하는 동안 대기(담기 전). 1000은 짧아 1개로 담기는 사례 → 1500.
const CONCURRENCY = 5; // 동시에 처리할 상품 탭 수(속도↑). 너무 크면 쿠팡 봇 의심/리소스 부담.
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

// 페이지 컨텍스트에서 실행: 상품 수량을 target 으로 맞춘다(async).
// 쿠팡 PDP 의 수량 컨트롤은 React 제어 input + 증가/감소 버튼이다.
// ⚠️ 함정: 버튼 '텍스트' 라벨이 뒤바뀌어 있다("수량빼기" 버튼이 실제로는 +).
//    실제 기능은 안쪽 <i> 아이콘(icon-plus=증가 / icon-minus=감소)을 따른다.
// 전략: 아이콘으로 inc/dec 판정 → 매 클릭 후 값 재확인하며 목표까지 수렴.
//       방향이 틀리면(거리 증가) 버튼을 자동 스왑, 값이 안 변하면(재고/한계) 중단.
// 반환: { status: "success"|"partial"|"notfound", set?, want, clicks }.
async function setQuantityInPage(target) {
  const want = Math.max(1, Number(target) || 1);
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const isVisible = (el) => !!(el && el.offsetParent !== null);
  const readNum = (el) => {
    const v = parseInt(((el && el.value) || "").trim(), 10);
    return Number.isFinite(v) ? v : null;
  };

  // 수량 입력칸: 숫자값 input (검색창 name=q / hidden 제외). 보이는 것 우선.
  const qtyInputs = Array.from(document.querySelectorAll("input")).filter(
    (el) => el.name !== "q" && el.type !== "hidden" && /^\d+$/.test(((el.value) || "").trim()),
  );
  const qtyInput = qtyInputs.find(isVisible) || qtyInputs[0] || null;

  // 스테퍼 버튼 후보: 아이콘(icon-plus/minus) 또는 라벨로. 보이는 것 우선, 없으면 전체.
  // (백그라운드 탭에서 레이아웃 미계산으로 offsetParent 가 null 일 수 있어 하드 필터하지 않음)
  const candAll = Array.from(document.querySelectorAll("button")).filter(
    (b) =>
      b.querySelector("i[class*='icon-plus'],i[class*='icon-minus']") ||
      /수량\s*더하기|수량\s*빼기|수량\s*증가|수량\s*감소/.test(b.textContent || ""),
  );
  const candVis = candAll.filter(isVisible);
  const cands = candVis.length ? candVis : candAll;

  if (!qtyInput || cands.length === 0) {
    return {
      status: qtyInput && cands.length ? "partial" : "notfound",
      set: readNum(qtyInput),
      want,
    };
  }

  // 아이콘 클래스로 inc/dec 판정(라벨 신뢰 불가). 못 찾으면 후보 순서로 배정.
  let incBtn = cands.find((b) => b.querySelector("i[class*='icon-plus']")) || null;
  let decBtn = cands.find((b) => b.querySelector("i[class*='icon-minus']")) || null;
  if (!incBtn) incBtn = cands.find((b) => b !== decBtn) || cands[0];
  if (!decBtn) decBtn = cands.find((b) => b !== incBtn) || cands[0];

  // 목표까지 한 클릭씩 수렴(자기보정: 역방향이면 스왑, 정체면 중단).
  let clicks = 0;
  let swapped = false;
  let lastDist = null;
  let stuck = 0;
  const MAX = 99;
  while (clicks < MAX) {
    const cur = readNum(qtyInput);
    if (cur == null || cur === want) break;
    const dist = Math.abs(cur - want);
    if (lastDist != null) {
      if (dist > lastDist && !swapped) {
        const t = incBtn;
        incBtn = decBtn;
        decBtn = t;
        swapped = true;
      } else if (dist === lastDist) {
        if (++stuck >= 2) break;
      } else {
        stuck = 0;
      }
    }
    lastDist = dist;
    const btn = cur < want ? incBtn : decBtn;
    if (!btn) break;
    btn.click();
    clicks++;
    await sleep(120);
  }

  const after = readNum(qtyInput);
  return { status: after === want ? "success" : "partial", set: after, want, clicks };
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

// 수량이 렌더될 때까지 짧게 재시도하며 target 으로 맞춘다.
async function setQuantityWithRetry(tabId, target) {
  for (let i = 0; i < CLICK_ATTEMPTS; i++) {
    try {
      const injected = await chrome.scripting.executeScript({
        target: { tabId },
        func: setQuantityInPage,
        args: [target],
      });
      const r = injected && injected[0] && injected[0].result;
      if (r && (r.status === "success" || r.status === "partial")) return r;
    } catch (e) {
      // 페이지 로딩 중 → 재시도
    }
    await delay(CLICK_GAP_MS);
  }
  return { status: "notfound" };
}

async function processItem(item) {
  const name = item.ingredient;
  const url = item.productUrl;
  const mode = item.addMode === "adjust" ? "adjust" : "direct";
  const qty = Math.max(1, Number(item.quantity) || 1);
  if (!url) {
    return { itemName: name, status: "skipped", message: "상품 URL이 없어 건너뛰었습니다." };
  }
  // adjust(수량조정) 여부. 탭은 백그라운드로 연다(direct 와 동일, 화면 방해 없음).
  const isAdjust = mode === "adjust" && qty > 1;
  let tab;
  try {
    tab = await chrome.tabs.create({ url, active: false });
    await waitForTabComplete(tab.id);
    // adjust 모드: 담기 전에 수량을 맞춘다. (실패해도 담기는 시도하되 메시지로 알림)
    let qtyNote = "";
    if (isAdjust) {
      await delay(400); // 수량 컨트롤 하이드레이션 여유.
      const q = await setQuantityWithRetry(tab.id, qty);
      if (q.status === "notfound") qtyNote = ` (수량 조절칸을 못 찾아 기본 수량으로 담음, 목표 ${qty}개)`;
      else if (q.status === "partial") qtyNote = ` (수량 ${q.set ?? "?"}/${qty}개까지만 조절됨)`;
      else qtyNote = ` (수량 ${qty}개)`;
      // 수량 변경 후 쿠팡이 로딩(옵션/가격 재계산)을 끝내야 담기에 새 수량이 반영된다.
      await delay(QTY_SETTLE_MS);
    }
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
        message: "장바구니 담기 완료." + qtyNote + " (결제는 진행하지 않음)",
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
  const results = new Array(total);

  // 동시 실행 상한(CONCURRENCY)을 둔 워커 풀: 항목을 병렬로 처리하되 한꺼번에 다 열지는 않는다.
  let next = 0;
  let done = 0;
  async function worker() {
    while (true) {
      const i = next++;
      if (i >= total) return;
      sendProgress(senderTabId, reqId, {
        phase: "item-start",
        index: i,
        total,
        itemName: items[i].ingredient,
      });
      const r = await processItem(items[i]);
      results[i] = r;
      done++;
      sendProgress(senderTabId, reqId, {
        phase: "item-done",
        index: i,
        total,
        done,
        result: r,
      });
    }
  }
  const workers = [];
  for (let k = 0; k < Math.min(CONCURRENCY, total); k++) workers.push(worker());
  await Promise.all(workers);

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
