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
const CART_CONFIRM_TIMEOUT_MS = 4000;
const CART_CONFIRM_GAP_MS = 500;
const CART_NAV_SETTLE_MS = 1200;
const QTY_SETTLE_MS = 1500; // 수량 변경 후 쿠팡이 옵션/가격 재계산하는 동안 대기(담기 전). 1000은 짧아 1개로 담기는 사례 → 1500.
const SEARCH_RESULT_LIMIT = 24;
const SEARCH_RENDER_ATTEMPTS = 10;
const SEARCH_RENDER_GAP_MS = 800;
const SEARCH_MIN_GAP_MS = 4000;
const SEARCH_MAX_GAP_MS = 7000;
const SEARCH_BATCH_SIZE = 5;
const SEARCH_BATCH_COOLDOWN_MS = 15000;
const CART_ITEM_MIN_GAP_MS = 1000;
const CART_ITEM_MAX_GAP_MS = 1800;
const CART_PAGE_URL = "https://cart.coupang.com/";

// 페이지 컨텍스트에서 실행: 장바구니 담기 버튼만 찾아 클릭.
function clickAddToCartInPage() {
  const FORBIDDEN = ["바로구매", "구매하기", "결제", "주문"];
  const textOf = (el) =>
    [
      el.innerText,
      el.textContent,
      el.value,
      el.getAttribute?.("aria-label"),
      el.getAttribute?.("title"),
    ]
      .filter(Boolean)
      .join(" ")
      .replace(/\s+/g, " ")
      .trim();
  const isForbidden = (el) => {
    const href = (el.getAttribute && el.getAttribute("href")) || "";
    if (/cart\.coupang\.com/.test(href)) return true;
    const text = textOf(el);
    return (
      FORBIDDEN.some((word) => text.includes(word)) ||
      Boolean(el.closest?.("header, nav, [role='navigation']"))
    );
  };
  const selectors = [
    "button.prod-cart-btn",
    "button[class*='prod-cart']",
    "button[class*='add-to-cart' i]",
    "button[class*='addToCart']",
    "[role='button'][class*='prod-cart']",
    "button, [role='button'], input[type=button], input[type=submit], a",
  ];
  const seen = new Set();
  const els = selectors.flatMap((selector) =>
    Array.from(document.querySelectorAll(selector)).filter((el) => {
      if (seen.has(el)) return false;
      seen.add(el);
      return true;
    }),
  );
  const scored = els
    .filter((el) => !isForbidden(el))
    .map((el) => {
      const text = textOf(el);
      const className =
        typeof el.className === "string" ? el.className.toLowerCase() : "";
      const dataAction = String(
        el.getAttribute?.("data-action") ||
          el.getAttribute?.("data-testid") ||
          "",
      ).toLowerCase();
      let score = 0;
      if (text.includes("장바구니 담기")) score += 100;
      else if (/장바구니에?\s*담기/.test(text)) score += 90;
      else if (text === "장바구니" || text.includes("장바구니")) score += 70;
      if (/prod-cart|add-to-cart|addtocart/.test(className)) score += 50;
      if (/cart/.test(dataAction)) score += 40;
      if (el.tagName === "BUTTON") score += 10;
      return { el, text, score };
    })
    .filter((candidate) => candidate.score >= 50)
    .sort((a, b) => b.score - a.score);
  const candidate = scored[0];
  const btn = candidate?.el;
  if (!btn) {
    return {
      status: "notfound",
      pageTitle: document.title,
      pageUrl: location.href,
      buttonTexts: els
        .map(textOf)
        .filter(Boolean)
        .filter((text) => text.length <= 40)
        .slice(0, 12),
    };
  }
  if (btn.disabled || btn.getAttribute("aria-disabled") === "true") {
    return {
      status: "disabled",
      buttonText: candidate.text,
      pageTitle: document.title,
      pageUrl: location.href,
    };
  }
  const readCartCount = () => {
    const candidates = Array.from(
      document.querySelectorAll(
        ".my-cart-count, #cart-count, [class*='cart-count'], [class*='CartCount']",
      ),
    );
    for (const el of candidates) {
      const match = String(el.textContent || "").match(/\d+/);
      if (match) return Number(match[0]);
    }
    return null;
  };
  try {
    btn.scrollIntoView({ block: "center" });
    const beforeCartCount = readCartCount();
    btn.click();
    return {
      status: "clicked",
      beforeCartCount,
      buttonText: candidate.text,
    };
  } catch (e) {
    return { status: "error" };
  }
}

function verifyCartAddInPage(beforeCartCount) {
  const bodyText = document.body?.innerText || document.body?.textContent || "";
  const successText =
    /장바구니에\s*(상품이\s*)?담겼|상품을\s*장바구니에\s*담았|장바구니\s*담기\s*완료/i.test(
      bodyText,
    );
  const errorText =
    /옵션을\s*선택|품절|구매할\s*수\s*없|로그인이\s*필요|성인인증/i.test(bodyText);
  const candidates = Array.from(
    document.querySelectorAll(
      ".my-cart-count, #cart-count, [class*='cart-count'], [class*='CartCount']",
    ),
  );
  let cartCount = null;
  for (const el of candidates) {
    const match = String(el.textContent || "").match(/\d+/);
    if (match) {
      cartCount = Number(match[0]);
      break;
    }
  }
  return {
    confirmed:
      successText ||
      (beforeCartCount != null && cartCount != null && cartCount > beforeCartCount),
    errorText,
    cartCount,
  };
}

function verifyProductInCartPage(productUrl, productName) {
  const identity = (() => {
    try {
      const url = new URL(productUrl);
      return {
        productId: url.pathname.match(/\/vp\/products\/(\d+)/)?.[1] || "",
        itemId: url.searchParams.get("itemId") || "",
        vendorItemId: url.searchParams.get("vendorItemId") || "",
      };
    } catch (e) {
      return { productId: "", itemId: "", vendorItemId: "" };
    }
  })();
  const roots = Array.from(
    document.querySelectorAll(
      "[class*='cart-deal-item'], [class*='cart-item'], [class*='CartItem'], " +
        "[data-vendor-item-id], [data-product-id], li",
    ),
  );
  const normalize = (value) =>
    String(value || "")
      .toLowerCase()
      .replace(/[^0-9a-z가-힣]/g, "");
  const normalizedName = normalize(productName);
  const namePrefix = normalizedName.slice(0, Math.min(14, normalizedName.length));
  const productLinks = Array.from(
    document.querySelectorAll("a[href*='/vp/products/'], a[href*='/products/']"),
  );
  for (const link of productLinks) {
    const href = link.href || link.getAttribute("href") || "";
    const linkText = normalize(
      link.innerText ||
        link.textContent ||
        link.getAttribute("aria-label") ||
        link.getAttribute("title"),
    );
    const idMatched =
      (identity.vendorItemId && href.includes(identity.vendorItemId)) ||
      (identity.itemId && href.includes(identity.itemId)) ||
      (identity.productId &&
        new RegExp(`/products/${identity.productId}(?:[/?#]|$)`).test(href));
    const nameMatched =
      namePrefix.length >= 6 &&
      linkText.length >= 6 &&
      (linkText.includes(namePrefix) || namePrefix.includes(linkText));
    if (idMatched || nameMatched) {
      return {
        confirmed: true,
        matchType: idMatched ? "product-link-id" : "product-link-name",
      };
    }
  }
  for (const root of roots) {
    const html = root.innerHTML || "";
    const text = normalize(root.innerText || root.textContent);
    const idMatched =
      (identity.vendorItemId && html.includes(identity.vendorItemId)) ||
      (identity.itemId && html.includes(identity.itemId)) ||
      (identity.productId && html.includes(`/products/${identity.productId}`));
    const nameMatched =
      namePrefix.length >= 6 &&
      text.length >= 6 &&
      (text.includes(namePrefix) || namePrefix.includes(text.slice(0, namePrefix.length)));
    if (idMatched || nameMatched) {
      return {
        confirmed: true,
        matchType: idMatched ? "product-id" : "product-name",
      };
    }
  }
  const bodyText = document.body?.innerText || "";
  return {
    confirmed: false,
    loginRequired: /로그인|이메일|휴대폰번호/.test(bodyText) && /비밀번호/.test(bodyText),
    emptyCart: /장바구니에\s*담긴\s*상품이\s*없|장바구니가\s*비어/.test(bodyText),
    pageTitle: document.title,
    pageUrl: location.href,
    productLinkCount: productLinks.length,
    cartRootCount: roots.length,
  };
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

function randomDelay(min, max) {
  return Math.floor(Math.random() * (max - min + 1)) + min;
}

function productIdentityKey(urlValue) {
  try {
    const url = new URL(urlValue);
    const productId = url.pathname.match(/\/vp\/products\/(\d+)/)?.[1] || "";
    const itemId = url.searchParams.get("itemId") || "";
    const vendorItemId = url.searchParams.get("vendorItemId") || "";
    if (vendorItemId) return `vendor:${vendorItemId}`;
    if (productId && itemId) return `product:${productId}:item:${itemId}`;
    if (productId) return `product:${productId}`;
    return url.toString();
  } catch (e) {
    return String(urlValue || "");
  }
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
  const cleanProductUrl = (href) => {
    try {
      const source = new URL(href, location.origin);
      const clean = new URL(source.pathname, source.origin);
      for (const key of ["itemId", "vendorItemId"]) {
        const value = source.searchParams.get(key);
        if (value) clean.searchParams.set(key, value);
      }
      return clean.toString();
    } catch (e) {
      return "";
    }
  };
  const parsePrice = (text) => {
    const source = String(text || "");
    const matched = source.match(/([\d,]{2,})\s*원/) || source.match(/[\d,]{2,}/);
    const digits = String(matched?.[1] || matched?.[0] || "").replace(/[^\d]/g, "");
    const value = Number(digits);
    return Number.isFinite(value) && value > 0 ? value : null;
  };
  // 상품명에서 용량 추정: 숫자+단위 × 멀티팩. 못 구하면 null.
  // 무게(g)·부피(ml)를 기본단위로 반환(kg/l/리터/킬로만 ×1000). 검색 단위와 같은 계열끼리 비교.
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
    const absolute = absoluteUrl(href);
    const url = cleanProductUrl(href);
    const pid = productId(absolute);
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

    let name = firstText(root, [
      ".name",
      ".search-product-name",
      "[class*='productName']",
      "[class*='ProductUnit_productName']",
    ]);
    if (!name) name = (link.getAttribute("title") || link.getAttribute("aria-label") || "").trim();
    if (!name) {
      const img = root.querySelector("img");
      name = img ? (img.getAttribute("alt") || "").trim() : "";
    }
    if (!name) name = (link.innerText || link.textContent || "").trim().split("\n")[0];
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
    const isRocket = /로켓/.test(allText) || !!rocketEl;
    const delivery = firstText(root, [
      ".arrival-info",
      ".delivery",
      "[class*='delivery']",
      "[class*='Delivery']",
    ]);

    if (!price) continue;

    byKey.set(key, {
      name,
      price,
      url, // 상품 경로와 itemId/vendorItemId만 유지해 선택 옵션으로 바로 이동.
      isAd,
      isRocket,
      // 용량은 카드 전체 텍스트에서 파싱(상품명 앵커가 제목만일 때도 "150g, 1개" 등 확보).
      amountG: parseAmountG(allText) ?? parseAmountG(name),
      delivery,
    });
    order.push(key);
  }
  const candidates = order.map((key) => byKey.get(key));
  const bodyText = document.body?.innerText || document.body?.textContent || "";
  return {
    candidates,
    pageTitle: document.title,
    blocked: /접근이 제한|자동화된 접근|captcha|로봇이 아닙니다|RET9999|시스템 오류 발생/i.test(bodyText),
    productLinkCount: anchors.length,
  };
}

function normalizeSearchText(value) {
  return String(value || "").toLowerCase().replace(/\s+/g, "");
}

// 선호(preference)에 따른 단일 최우선 정렬(가중치 혼합 아님).
//  - price/기본 → 최저가
//  - speed → 로켓 상품 먼저, 그 안에서 최저가
// 단, 항상 (1) 재료명 관련성, (2) 광고 여부를 앞 기준으로 둔다(엉뚱/광고 상품 방지).
function rankSearchCandidates(ingredient, candidates, preference) {
  const needle = normalizeSearchText(ingredient);
  const SEARCH_ALIASES = {
    계란: ["달걀", "대란", "특란", "왕란", "중란"],
    달걀: ["계란", "대란", "특란", "왕란", "중란"],
  };
  const searchTerms = Array.from(
    new Set([needle, ...(SEARCH_ALIASES[needle] || [])].filter(Boolean)),
  );
  const tokens = String(ingredient || "")
    .split(/\s+/)
    .filter(Boolean)
    .map(normalizeSearchText);
  const esc = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const boundaryRes = searchTerms.map(
    (term) => new RegExp(esc(term) + "(?![가-힣])"),
  );
  // 가공형 접미사 — 재료명에 없을 때만 강등(예: 생강 vs 생강차/생강즙. 단 고춧'가루'는 재료명에 있어 제외).
  const PROCESSED = [
    "차", "청", "즙", "환", "진액", "엑기스", "농축", "정과", "절임", "장아찌",
    "캔디", "사탕", "시럽", "페이스트", "티백", "음료", "스틱", "식초", "분말", "가루",
    "김치", "양념", "허브", "시즈닝", "레몬머틀", "와사비",
    "트러플", "갈릭", "버터",
  ];
  const EGG_PROCESSED = [
    "구운계란", "구운달걀", "훈제계란", "훈제달걀", "훈제란",
    "반숙란", "반숙계란", "반숙달걀", "계란과자", "달걀과자",
  ];
  const isProcessed = (hay) => {
    if (
      (needle === "계란" || needle === "달걀") &&
      EGG_PROCESSED.some((word) => hay.includes(word))
    ) {
      return true;
    }
    return searchTerms.some((term) =>
      PROCESSED.some(
        (word) =>
          !needle.includes(word) &&
          (hay.includes(`${term}${word}`) || hay.includes(`${word}${term}`)),
      ),
    );
  };
  const relevance = (name) => {
    const hay = normalizeSearchText(name);
    let base;
    const exactTermIndex = searchTerms.findIndex((term) => hay.includes(term));
    if (exactTermIndex >= 0) {
      // 재료명 뒤에 한글이 또 붙으면(생강'차') 약하게, 단어 경계로 끝나면(흙생강) 강하게.
      base = boundaryRes[exactTermIndex].test(hay) ? 3 : 2;
    } else {
      // bigram 겹침 — 어순/접미사 차이("마늘다진것"↔"다진마늘") 대응.
      let hits = 0;
      for (let i = 0; needle && i + 2 <= needle.length; i++) {
        if (hay.includes(needle.slice(i, i + 2))) hits++;
      }
      const requiredHits = Math.min(
        3,
        Math.max(1, Math.ceil(Math.max(0, needle.length - 1) * 0.5)),
      );
      const tokenHits = tokens.filter((t) => t.length >= 2 && hay.includes(t)).length;
      base =
        hits >= requiredHits
          ? 2
          : tokens.length > 1 && tokenHits > 0
            ? 1
            : 0;
    }
    if (base > 0 && isProcessed(hay)) base = 0;
    return base;
  };
  // 쿠팡이 이미 '낮은 가격순(salePriceAsc)'으로 정렬해 주므로 우리는 재정렬하지 않는다.
  //  (1) 관련 있는 것만(가공품/광고/무관 제거) (2) 빠른배송이면 로켓만 (3) 쿠팡 순서(=최저가) 유지.
  let list = candidates
    .map((c, i) => ({ ...c, score: relevance(c.name), _i: i }))
    .filter((c) => c.score > 0 && !c.isAd && c.price > 0);
  if (list.length === 0) return [];
  if (preference === "speed") {
    const rocket = list.filter((c) => c.isRocket);
    if (rocket.length) list = rocket; // 로켓 없으면 폴백
  }
  // 관련성 높은 순 → 쿠팡 원래 순서(낮은 가격순) 유지(stable sort).
  return list.sort((a, b) => b.score - a.score || a._i - b._i);
}

async function tabExists(tabId) {
  if (!tabId) return false;
  try {
    await chrome.tabs.get(tabId);
    return true;
  } catch (e) {
    return false;
  }
}

async function closeTabQuietly(tabId) {
  if (!tabId) return;
  try {
    if (await tabExists(tabId)) await chrome.tabs.remove(tabId);
  } catch (e) {}
}

async function openOrReuseSearchTab(tabId, searchUrl) {
  if (await tabExists(tabId)) {
    for (let attempt = 0; attempt < 5; attempt++) {
      try {
        const tab = await chrome.tabs.update(tabId, { url: searchUrl, active: false });
        return tab.id;
      } catch (e) {
        const message = String(e?.message || e);
        if (!/Tabs cannot be edited right now/i.test(message)) throw e;
        await delay(500 + attempt * 500);
      }
    }
    await closeTabQuietly(tabId);
  }
  const tab = await chrome.tabs.create({ url: searchUrl, active: false });
  return tab.id;
}

async function extractCandidatesWithRetry(tabId) {
  let result = null;
  for (let attempt = 0; attempt < SEARCH_RENDER_ATTEMPTS; attempt++) {
    if (attempt > 0) await delay(SEARCH_RENDER_GAP_MS);
    const injected = await chrome.scripting.executeScript({
      target: { tabId },
      func: extractSearchCandidatesInPage,
      args: [SEARCH_RESULT_LIMIT],
    });
    result = injected && injected[0] && injected[0].result;
    if (result?.blocked || result?.candidates?.length > 0) break;
  }
  return result;
}

async function searchOneIngredient(item, reusableTabId) {
  const ingredient = item.ingredient;
  const neededAmount = Number(item.neededAmount) || null;
  const neededUnit = item.neededUnit === "ml" ? "ml" : "g"; // 무게 g / 부피 ml
  // 필요량(무게 g / 부피 ml)이 있으면 검색어에 용량을 붙여, 쿠팡이 비슷한 용량 상품을 우선 노출하게 한다.
  const query = neededAmount ? `${ingredient} ${neededAmount}${neededUnit}` : ingredient;
  // 쿠팡 정렬/필터를 그대로 사용: 낮은 가격순(salePriceAsc) + (빠른배송면) 로켓 필터.
  const params = new URLSearchParams({
    q: query,
    channel: "user",
    listSize: "36",
    sorter: "salePriceAsc",
  });
  if (item.preference === "speed") {
    params.set("filterType", "rocket_luxury,rocket_wow,coupang_global");
    params.set("rocketAll", "true");
  }
  const searchUrl = `https://www.coupang.com/np/search?${params.toString()}`;
  let tabId = reusableTabId;
  let lastError = null;

  for (let attempt = 0; attempt < 2; attempt++) {
    try {
      tabId = await openOrReuseSearchTab(tabId, searchUrl);
      await waitForTabComplete(tabId);
      const result = await extractCandidatesWithRetry(tabId);
      const candidates = rankSearchCandidates(
        ingredient,
        result?.candidates || [],
        item.preference,
      );
      const selected = candidates[0] || null;

      let addMode = "direct";
      let quantity = 1;
      let qtyNote = "";
      if (selected && neededAmount && selected.amountG) {
        if (selected.amountG >= neededAmount) {
          qtyNote = ` (필요 ${neededAmount}${neededUnit} ≤ 상품 ${selected.amountG}${neededUnit} → 1개)`;
        } else {
          addMode = "adjust";
          quantity = Math.max(1, Math.ceil(neededAmount / selected.amountG));
          qtyNote = ` (필요 ${neededAmount}${neededUnit} / 상품 ${selected.amountG}${neededUnit} → ${quantity}개)`;
        }
      } else if (selected && neededAmount && !selected.amountG) {
        qtyNote = " (상품 용량 미확인 → 1개)";
      }

      return {
        tabId,
        result: {
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
              : `상품 링크 ${result?.productLinkCount || 0}개를 확인했지만 안전하게 확정할 관련 상품이 없습니다.`,
        },
      };
    } catch (e) {
      lastError = e;
      const message = String(e?.message || e);
      if (!/No tab with id|Tabs cannot be edited right now/i.test(message) || attempt > 0) {
        break;
      }
      tabId = null;
      await delay(1000);
    }
  }

  return {
    tabId,
    result: {
      ingredient,
      status: "failed",
      searchUrl,
      selected: null,
      candidates: [],
      message: "상품 검색에 실패했습니다: " +
        (lastError && lastError.message ? lastError.message : lastError),
    },
  };
}

async function searchProducts(items, senderTabId, reqId) {
  const results = [];
  let done = 0;
  let searchTabId = null;

  try {
    for (let i = 0; i < items.length; i++) {
      if (i > 0) {
        await delay(
          i % SEARCH_BATCH_SIZE === 0
            ? SEARCH_BATCH_COOLDOWN_MS
            : randomDelay(SEARCH_MIN_GAP_MS, SEARCH_MAX_GAP_MS),
        );
      }
      sendProgress(senderTabId, reqId, {
        phase: "search-start",
        index: i,
        total: items.length,
        itemName: items[i].ingredient,
      }, "FRIDGEMATE_SEARCH_PROGRESS");
      const searched = await searchOneIngredient(items[i], searchTabId);
      searchTabId = searched.tabId;
      const result = searched.result;
      results.push(result);
      done++;
      sendProgress(senderTabId, reqId, {
        phase: "search-done",
        index: i,
        total: items.length,
        done,
        result,
      }, "FRIDGEMATE_SEARCH_PROGRESS");

      if (result.status === "blocked") {
        for (let j = i + 1; j < items.length; j++) {
          results.push({
            ingredient: items[j].ingredient,
            status: "blocked",
            searchUrl: `https://www.coupang.com/np/search?q=${encodeURIComponent(items[j].ingredient)}`,
            selected: null,
            candidates: [],
            message: "접근 제한을 감지해 남은 자동 검색을 중단했습니다.",
          });
        }
        break;
      }
    }
  } finally {
    await closeTabQuietly(searchTabId);
  }

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
  let lastResult = null;
  for (let i = 0; i < CLICK_ATTEMPTS; i++) {
    try {
      const injected = await chrome.scripting.executeScript({
        target: { tabId },
        func: clickAddToCartInPage,
      });
      const r = injected && injected[0] && injected[0].result;
      lastResult = r || lastResult;
      if (r && r.status === "clicked") {
        return {
          ok: true,
          beforeCartCount: r.beforeCartCount,
          buttonText: r.buttonText,
        };
      }
      if (r?.status === "disabled") {
        return {
          ok: false,
          reason: "disabled",
          detail: r.buttonText || "",
        };
      }
    } catch (e) {
      // 페이지가 아직 로딩 중일 수 있음 → 재시도
    }
    await delay(CLICK_GAP_MS);
  }
  return {
    ok: false,
    reason: lastResult?.status || "notfound",
    detail:
      lastResult?.buttonTexts?.join(" / ") ||
      lastResult?.buttonText ||
      lastResult?.pageTitle ||
      "",
  };
}

async function waitForCartConfirmation(tabId, beforeCartCount) {
  const started = Date.now();
  while (Date.now() - started < CART_CONFIRM_TIMEOUT_MS) {
    try {
      const injected = await chrome.scripting.executeScript({
        target: { tabId },
        func: verifyCartAddInPage,
        args: [beforeCartCount],
      });
      const result = injected && injected[0] && injected[0].result;
      if (result?.confirmed) return { confirmed: true, via: "product-page" };
      if (result?.errorText) return { confirmed: false, reason: "product-error" };
    } catch (e) {}
    await delay(CART_CONFIRM_GAP_MS);
  }
  return { confirmed: false, reason: "unconfirmed" };
}

async function verifyProductInCart(tabId, productUrl, productName) {
  await delay(CART_NAV_SETTLE_MS);
  await chrome.tabs.update(tabId, { url: CART_PAGE_URL, active: false });
  await waitForTabComplete(tabId);
  let lastResult = null;
  for (let attempt = 0; attempt < 12; attempt++) {
    if (attempt > 0) await delay(500);
    try {
      const injected = await chrome.scripting.executeScript({
        target: { tabId },
        func: verifyProductInCartPage,
        args: [productUrl, productName || ""],
      });
      const result = injected && injected[0] && injected[0].result;
      lastResult = result || lastResult;
      if (result?.confirmed) return { confirmed: true, via: "cart-page" };
      if (result?.loginRequired) return { confirmed: false, reason: "login-required" };
      if (result?.emptyCart) return { confirmed: false, reason: "empty-cart" };
    } catch (e) {}
  }
  return {
    confirmed: false,
    reason: "cart-item-not-found",
    detail: lastResult
      ? `상품 링크 ${lastResult.productLinkCount ?? 0}개, 후보 영역 ${lastResult.cartRootCount ?? 0}개`
      : "장바구니 화면을 읽지 못함",
  };
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
  const productName = item.productName;
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
    const clicked = await clickWithRetry(tab.id);
    if (clicked.ok) {
      const pageSignal = await waitForCartConfirmation(
        tab.id,
        clicked.beforeCartCount,
      );
      if (pageSignal.reason === "product-error") {
        return {
          itemName: name,
          productName,
          productUrl: url,
          status: "failed",
          message: "상품 옵션·품절 안내가 표시되어 담지 못했습니다.",
        };
      }

      // 상품 페이지의 토스트나 헤더 숫자는 오탐 가능성이 있다. 최종 성공은
      // 장바구니 페이지에서 선택한 상품 ID를 직접 찾았을 때만 인정한다.
      const verification = await verifyProductInCart(tab.id, url, productName);
      if (!verification.confirmed) {
        const reason =
          verification.reason === "login-required"
            ? "쿠팡 로그인이 필요합니다."
            : verification.reason === "empty-cart"
              ? "쿠팡 장바구니가 비어 있습니다. 담기 요청이 반영되지 않았습니다."
              : `장바구니에서 선택 상품을 확인하지 못했습니다. (${verification.detail || "확인 정보 없음"})`;
        return {
          itemName: name,
          productName,
          productUrl: url,
          status: "failed",
          message: reason,
        };
      }
      return {
        itemName: name,
        productName,
        productUrl: url,
        status: "success",
        message:
          "장바구니 반영 확인 완료." +
          qtyNote +
          " (결제는 진행하지 않음)",
      };
    }
    return {
      itemName: name,
      productName,
      productUrl: url,
      status: "failed",
      message:
        clicked.reason === "disabled"
          ? `장바구니 버튼이 비활성 상태입니다. 상품 옵션 확인이 필요합니다.${clicked.detail ? ` (${clicked.detail})` : ""}`
          : `장바구니 버튼을 찾지 못했습니다.${clicked.detail ? ` 페이지 버튼: ${clicked.detail}` : ""}`,
    };
  } catch (e) {
    return {
      itemName: name,
      productName,
      productUrl: url,
      status: "failed",
      message: "상품 페이지 처리에 실패했습니다: " + (e && e.message ? e.message : e),
    };
  } finally {
    await closeTabQuietly(tab?.id);
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
  const claimedProducts = new Map();
  let done = 0;

  for (let i = 0; i < total; i++) {
    if (i > 0) {
      await delay(randomDelay(CART_ITEM_MIN_GAP_MS, CART_ITEM_MAX_GAP_MS));
    }
    sendProgress(senderTabId, reqId, {
      phase: "item-start",
      index: i,
      total,
      itemName: items[i].ingredient,
    });
    const item = items[i];
    const identity = item.productUrl ? productIdentityKey(item.productUrl) : "";
    const claimedBy = identity ? claimedProducts.get(identity) : null;
    let result;
    if (claimedBy && claimedBy !== item.ingredient) {
      result = {
        itemName: item.ingredient,
        productName: item.productName,
        productUrl: item.productUrl,
        status: "failed",
        message:
          `"${claimedBy}"와 동일한 쿠팡 상품이 선택되어 중복 담기를 중단했습니다. ` +
          "검색 결과에서 다른 상품을 선택해야 합니다.",
      };
    } else {
      result = await processItem(item);
      if (identity && result.status === "success") {
        claimedProducts.set(identity, item.ingredient);
      }
    }
    results[i] = result;
    done++;
    sendProgress(senderTabId, reqId, {
      phase: "item-done",
      index: i,
      total,
      done,
      result,
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
  } else if (msg && msg.type === "FRIDGEMATE_SEARCH_PRODUCTS" && sender.tab) {
    searchProducts(msg.items || [], sender.tab.id, msg.reqId);
  }
  return false;
});
