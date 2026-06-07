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
const SEARCH_CONCURRENCY = 2;
const SEARCH_RESULT_LIMIT = 24;
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

// 페이지 컨텍스트에서 실행: 쿠팡 검색 결과 카드에서 상품 정보를 추출한다.
// 쿠팡 DOM 변경에 대비해 data-product-id와 상품 링크를 함께 사용한다.
function extractSearchCandidatesInPage(limit) {
  const absoluteUrl = (href) => {
    try {
      return new URL(href, location.origin).toString();
    } catch (e) {
      return "";
    }
  };
  const parsePrice = (text) => {
    const digits = String(text || "").replace(/[^\d]/g, "");
    const value = Number(digits);
    return Number.isFinite(value) && value > 0 ? value : null;
  };
  // 상품명에서 용량(그램 가정) 추정: 숫자+단위 × 멀티팩. 못 구하면 null.
  // (단순화: 모든 단위를 g로 본다. kg/l/리터/킬로만 ×1000.)
  const parseAmountG = (text) => {
    const s = String(text || "");
    // 용량(첫 번째 숫자+단위). "(10g당 …)" 단가 표기는 뒤에 오므로 보통 영향 없음.
    const m = s.match(/(\d+(?:[.,]\d+)?)\s*(kg|g|l|ml|그램|킬로|리터)/i);
    if (!m) return null;
    let v = parseFloat(m[1].replace(",", ""));
    const u = m[2].toLowerCase();
    if (u === "kg" || u === "l" || u === "리터" || u === "킬로") v *= 1000;
    // 수량(팩): "30개", "1통", "2세트", "×3" 등 → 용량 × 수량 = 리스팅 총량.
    let pack = 1;
    const pm =
      s.match(/[x×]\s*(\d+)/) ||
      s.match(/(\d+)\s*(?:개입|개|통|세트|팩|봉|입|매)/);
    if (pm) pack = Number(pm[1]) || 1;
    const total = Math.round(v * pack);
    return Number.isFinite(total) && total > 0 ? total : null;
  };
  const firstText = (root, selectors) => {
    for (const selector of selectors) {
      const el = root.querySelector(selector);
      const text = (el && (el.innerText || el.textContent) || "").trim();
      if (text) return text;
    }
    return "";
  };

  const productId = (url) => {
    const m = String(url).match(/\/vp\/products\/(\d+)/);
    return m ? m[1] : null;
  };

  // 앵커(/vp/products/ 링크) 기반 추출: 쿠팡 카드 클래스가 바뀌어도 견고.
  // ⚠️ 같은 상품ID라도 1kg/3kg/5kg 는 vendorItemId 가 다른 '별도 옵션 카드'다.
  //    이름과 URL(옵션)이 어긋나면 안 되므로 옵션(vendorItemId)별로 따로 후보를 만든다.
  //    옵션이 박힌 href 라야 검색에서 본 그 옵션이 그대로 담긴다(아니면 상품 기본옵션이 담김).
  const optionId = (href) => {
    const v = String(href || "").match(/[?&]vendorItemId=(\d+)/);
    if (v) return "v" + v[1];
    const i = String(href || "").match(/[?&]itemId=(\d+)/);
    return i ? "i" + i[1] : null;
  };
  const anchors = Array.from(
    document.querySelectorAll('a[href*="/vp/products/"]'),
  );
  // 옵션 앵커가 하나라도 있는 상품ID 집계 → 그런 상품은 옵션 없는 앵커를 무시(기본옵션 담김 방지).
  const optionedPids = new Set();
  for (const link of anchors) {
    const href = link.getAttribute("href") || "";
    if (optionId(href)) {
      const pid = productId(absoluteUrl(href));
      if (pid) optionedPids.add(pid);
    }
  }

  const byKey = new Map();
  const order = [];
  for (const link of anchors) {
    const href = link.getAttribute("href") || "";
    const url = absoluteUrl(href);
    const pid = productId(url);
    if (!url || !pid) continue;
    const opt = optionId(href);
    // 옵션 카드가 존재하는 상품은 '옵션 앵커'만 사용(이름↔옵션 일치 보장).
    if (optionedPids.has(pid) && !opt) continue;
    const key = opt ? `${pid}:${opt}` : `${pid}`;
    if (byKey.has(key)) continue;
    if (order.length >= limit) continue;

    const root =
      link.closest("li, [data-product-id], .search-product") ||
      link.parentElement ||
      link;

    let name = (link.innerText || link.textContent || "").trim();
    if (!name) name = (link.getAttribute("title") || "").trim();
    if (!name) {
      const img = root.querySelector("img");
      name = img ? (img.getAttribute("alt") || "").trim() : "";
    }
    if (!name)
      name = firstText(root, [
        ".name",
        ".search-product-name",
        "[class*='productName']",
        "[class*='ProductUnit']",
      ]);
    if (!name) name = (root.innerText || root.textContent || "").trim().slice(0, 80);
    if (!name) continue;

    const allText = (root.innerText || root.textContent || "").trim();
    let price = parsePrice(
      firstText(root, [
        ".price-value",
        ".price strong",
        "[class*='price-value']",
        "[class*='Price_price']",
      ]),
    );
    if (!price) {
      const pm = allText.match(/([\d,]{2,})\s*원/);
      price = pm ? parsePrice(pm[1]) : null;
    }
    const isAd = /광고|AD\b/i.test(allText);
    // 로켓 배지는 텍스트가 아니라 이미지/아이콘인 경우가 많아 img(alt/src)·class 도 확인.
    const rocketEl = root.querySelector(
      "img[alt*='로켓'], img[src*='rocket' i], [class*='rocket' i]",
    );
    const freshEl = root.querySelector(
      "img[alt*='프레시'], img[src*='fresh' i], [class*='fresh' i]",
    );
    const isRocket = /로켓/.test(allText) || !!rocketEl;
    const isRocketFresh = /로켓\s*프레시/.test(allText) || !!freshEl;
    const delivery = firstText(root, [
      ".arrival-info",
      ".delivery",
      "[class*='delivery']",
      "[class*='Delivery']",
    ]);

    byKey.set(key, {
      name,
      price: price || 0,
      url, // 옵션 앵커의 href(vendorItemId 포함) → 담기 시 이 옵션 그대로.
      isAd,
      isRocket,
      isRocketFresh,
      // 용량은 카드 전체 텍스트에서 파싱(상품명 앵커가 제목만일 때도 "150g, 1개" 등 확보).
      amountG: parseAmountG(allText) ?? parseAmountG(name),
      delivery,
    });
    order.push(key);
  }
  const candidates = order.map((key) => byKey.get(key));
  return {
    candidates,
    pageTitle: document.title,
    blocked: /접근이 제한|자동화된 접근|captcha|로봇이 아닙니다/i.test(
      document.body?.innerText || "",
    ),
  };
}

function normalizeSearchText(value) {
  return String(value || "").toLowerCase().replace(/\s+/g, "");
}

// 선호(preference)에 따른 단일 최우선 정렬(가중치 혼합 아님).
//  - price/nutrition/기본 → 최저가
//  - speed → 로켓 상품 먼저, 그 안에서 최저가
//  - freshness → 로켓프레시 먼저, 그다음 로켓, 그 안에서 최저가
// 단, 항상 (1) 재료명 관련성, (2) 광고 여부를 앞 기준으로 둔다(엉뚱/광고 상품 방지).
function rankSearchCandidates(ingredient, candidates, preference, neededG) {
  const needle = normalizeSearchText(ingredient);
  const tokens = String(ingredient || "")
    .split(/\s+/)
    .filter(Boolean)
    .map(normalizeSearchText);
  const esc = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const boundaryRe = needle ? new RegExp(esc(needle) + "(?![가-힣])") : null;
  // 가공형 접미사 — 재료명에 없을 때만 강등(예: 생강 vs 생강차/생강즙. 단 고춧'가루'는 재료명에 있어 제외).
  const PROCESSED = [
    "차", "청", "즙", "환", "진액", "엑기스", "농축", "정과", "절임", "장아찌",
    "캔디", "사탕", "시럽", "페이스트", "티백", "음료", "스틱", "식초", "분말", "가루",
  ];
  const isProcessed = (hay) =>
    PROCESSED.some((w) => hay.includes(w) && !needle.includes(w));
  const relevance = (name) => {
    const hay = normalizeSearchText(name);
    let base;
    if (needle && hay.includes(needle)) {
      // 재료명 뒤에 한글이 또 붙으면(생강'차') 약하게, 단어 경계로 끝나면(흙생강) 강하게.
      base = boundaryRe && boundaryRe.test(hay) ? 3 : 2;
    } else {
      // bigram 겹침 — 어순/접미사 차이("마늘다진것"↔"다진마늘") 대응.
      let hits = 0;
      for (let i = 0; needle && i + 2 <= needle.length; i++) {
        if (hay.includes(needle.slice(i, i + 2))) hits++;
      }
      base = hits >= 2 ? 2 : hits === 1 || tokens.some((t) => t && hay.includes(t)) ? 1 : 0;
    }
    if (base > 0 && isProcessed(hay)) base = Math.max(0, base - 2); // 가공형 강등
    return base;
  };
  // 쿠팡이 이미 '낮은 가격순(salePriceAsc)'으로 정렬해 주므로 우리는 재정렬하지 않는다.
  //  (1) 관련 있는 것만(가공품/광고/무관 제거) (2) 빠른배송이면 로켓만 (3) 쿠팡 순서(=최저가) 유지.
  let list = candidates.map((c, i) => ({ ...c, score: relevance(c.name), _i: i }));
  const relevant = list.filter((c) => c.score > 0 && !c.isAd);
  if (relevant.length) list = relevant; // 관련 상품이 하나도 없으면 폴백으로 전체 유지
  if (preference === "speed") {
    const rocket = list.filter((c) => c.isRocket);
    if (rocket.length) list = rocket; // 로켓 없으면 폴백
  } else if (preference === "freshness") {
    const fresh = list.filter((c) => c.isRocketFresh);
    if (fresh.length) list = fresh;
  }
  // 관련성 높은 순 → 쿠팡 원래 순서(낮은 가격순) 유지(stable sort).
  return list.sort((a, b) => b.score - a.score || a._i - b._i);
}

async function searchOneIngredient(item) {
  const ingredient = item.ingredient;
  const neededG = Number(item.neededG) || null;
  // 필요 g 가 있으면 검색어에 용량을 붙여, 쿠팡이 비슷한 용량 상품을 우선 노출하게 한다.
  const query = neededG ? `${ingredient} ${neededG}g` : ingredient;
  // 쿠팡 정렬/필터를 그대로 사용: 낮은 가격순(salePriceAsc) + (빠른배송/신선도면) 로켓 필터.
  const params = new URLSearchParams({
    q: query,
    channel: "user",
    listSize: "36",
    sorter: "salePriceAsc",
  });
  if (item.preference === "speed" || item.preference === "freshness") {
    params.set("filterType", "rocket_luxury,rocket_wow,coupang_global");
    params.set("rocketAll", "true");
  }
  const searchUrl = `https://www.coupang.com/np/search?${params.toString()}`;
  let tab;
  try {
    tab = await chrome.tabs.create({ url: searchUrl, active: false });
    await waitForTabComplete(tab.id);
    await delay(1500); // 검색 결과 비동기 렌더 여유.
    const injected = await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      func: extractSearchCandidatesInPage,
      args: [SEARCH_RESULT_LIMIT],
    });
    const result = injected && injected[0] && injected[0].result;
    const candidates = rankSearchCandidates(
      ingredient,
      result?.candidates || [],
      item.preference,
      neededG,
    );
    const selected = candidates[0] || null;

    // 필요량(그램 가정) vs 상품 용량 → 담을 개수/방식 산정.
    let addMode = "direct";
    let quantity = 1;
    let qtyNote = "";
    if (selected && neededG && selected.amountG) {
      if (selected.amountG >= neededG) {
        addMode = "direct";
        quantity = 1;
        qtyNote = ` (필요 ${neededG}g ≤ 상품 ${selected.amountG}g → 1개)`;
      } else {
        addMode = "adjust";
        quantity = Math.max(1, Math.ceil(neededG / selected.amountG));
        qtyNote = ` (필요 ${neededG}g / 상품 ${selected.amountG}g → ${quantity}개)`;
      }
    } else if (selected && neededG && !selected.amountG) {
      qtyNote = " (상품 용량 미확인 → 1개)";
    }

    return {
      ingredient,
      status: selected ? "success" : result?.blocked ? "blocked" : "notfound",
      searchUrl,
      selected,
      candidates,
      addMode,
      quantity,
      message: selected
        ? `상품을 선택했습니다.${qtyNote}`
        : result?.blocked
          ? "쿠팡이 검색 페이지 접근을 제한했습니다. 잠시 후 다시 시도해 주세요."
          : "검색 결과에서 상품 정보를 찾지 못했습니다.",
    };
  } catch (e) {
    return {
      ingredient,
      status: "failed",
      searchUrl,
      selected: null,
      candidates: [],
      message: "상품 검색에 실패했습니다: " + (e && e.message ? e.message : e),
    };
  } finally {
    if (tab?.id) {
      try {
        await chrome.tabs.remove(tab.id);
      } catch (e) {}
    }
  }
}

async function searchProducts(items, senderTabId, reqId) {
  const results = new Array(items.length);
  let next = 0;
  let done = 0;
  async function worker() {
    while (true) {
      const i = next++;
      if (i >= items.length) return;
      sendProgress(senderTabId, reqId, {
        phase: "search-start",
        index: i,
        total: items.length,
        itemName: items[i].ingredient,
      }, "FRIDGEMATE_SEARCH_PROGRESS");
      results[i] = await searchOneIngredient(items[i]);
      done++;
      sendProgress(senderTabId, reqId, {
        phase: "search-done",
        index: i,
        total: items.length,
        done,
        result: results[i],
      }, "FRIDGEMATE_SEARCH_PROGRESS");
    }
  }
  const workers = [];
  for (let i = 0; i < Math.min(SEARCH_CONCURRENCY, items.length); i++) workers.push(worker());
  await Promise.all(workers);
  chrome.tabs.sendMessage(senderTabId, {
    type: "FRIDGEMATE_SEARCH_RESULT",
    reqId,
    response: { results },
  });
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

function sendProgress(senderTabId, reqId, payload, type = "FRIDGEMATE_EXEC_PROGRESS") {
  try {
    chrome.tabs.sendMessage(senderTabId, {
      type,
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
  } else if (msg && msg.type === "FRIDGEMATE_SEARCH_PRODUCTS" && sender.tab) {
    searchProducts(msg.items || [], sender.tab.id, msg.reqId);
  }
  return false;
});
