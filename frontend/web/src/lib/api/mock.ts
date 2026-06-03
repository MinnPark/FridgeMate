// FridgeMate AI - 프론트엔드 mock 데이터 (역할 D)
//
// 역할 D 원칙: AI/RAG/Tool/점수 계산 로직은 직접 구현하지 않는다.
// 그 결과가 존재한다고 가정하고 그럴듯한 mock 으로 채운다. 점수(제철/트렌드/상품)는
// 백엔드가 내려준다고 가정하고 값만 둔다(프론트에서 계산하지 않음).
//
// 기준 시나리오:
//   재료: 닭가슴살, 계란, 브로콜리, 두부 / 목표: 고단백·저탄수
//   단백질 120g·칼로리 1,700kcal / 예산 100,000원 / 2인 / 해산물 제외 / 20분 이내 / Goal

import type {
  CartResponse,
  FridgeMateRequest,
  IngredientEntry,
  RunResponse,
  ShoppingItem,
} from "./types";

// 데모 진입 시 보여줄 기본 재료(용량/유통기한 포함). 사용자가 추가/삭제 가능.
export const DEFAULT_INGREDIENT_ENTRIES: IngredientEntry[] = [
  { name: "닭가슴살", amount: "500g", expirationDate: "2025-05-20", storageType: "냉장 보관" },
  { name: "계란", amount: "10개", expirationDate: "2025-05-22", storageType: "냉장 보관" },
  { name: "브로콜리", amount: "300g", expirationDate: "2025-05-18", storageType: "냉장 보관" },
  { name: "두부", amount: "1모", expirationDate: "2025-05-16", storageType: "냉장 보관" },
];

export const DEMO_REQUEST: FridgeMateRequest = {
  ingredients: "닭가슴살, 계란, 브로콜리, 두부",
  mode: "goal",
  goal: "고단백 저탄수",
  proteinTargetGram: 120,
  calorieTargetKcal: 1700,
  budgetKrw: 100000,
  peopleCount: 2,
  excludedIngredients: "해산물",
  maxCookingMinutes: 20,
  deliveryPreference: "freshness",
};

const COUPANG_SEARCH = (names: string[]) =>
  `https://www.coupang.com/np/search?q=${names
    .map((n) => encodeURIComponent(n))
    .join("%20")}`;

function uid(prefix: string): string {
  return `${prefix}_${Math.random().toString(16).slice(2, 10)}`;
}

function parseIngredients(raw: string): string[] {
  return raw
    .split(/[,\n]/)
    .map((s) => s.trim())
    .filter(Boolean);
}

const SHOPPING_ITEMS: ShoppingItem[] = [
  {
    name: "현미",
    quantity: "1kg",
    priceKrw: 6900,
    reason: "저탄수 목표에 맞춘 잡곡 베이스",
    delivery: "내일 도착(로켓배송)",
    // 실제 쿠팡 상품 URL (테스트용). 실제로는 상품 추천 파이프라인이 채운다.
    productUrl:
      "https://www.coupang.com/vp/products/1221588314?itemId=2343407356&vendorItemId=70339972606",
    score: {
      shoppingScore: 88,
      deliveryScore: 82,
      priceScore: 90,
      freshnessScore: 85,
      nutritionFitScore: 91,
      reasons: ["영양 적합도 높음", "단가 대비 가성비 우수"],
    },
  },
  {
    name: "양파",
    quantity: "1.5kg (망)",
    priceKrw: 3980,
    reason: "강된장·볶음 공통 재료",
    delivery: "모레 도착",
    productUrl:
      "https://www.coupang.com/vp/products/1074470755?itemId=2573048645&vendorItemId=70565380605",
    score: {
      shoppingScore: 80,
      deliveryScore: 78,
      priceScore: 86,
      freshnessScore: 79,
      nutritionFitScore: 70,
      reasons: ["여러 레시피에 재사용 가능"],
    },
  },
  {
    name: "그릭요거트",
    quantity: "450g",
    priceKrw: 7200,
    reason: "단백질 보강용 간식",
    delivery: "내일 도착(로켓프레시)",
    score: {
      shoppingScore: 84,
      deliveryScore: 88,
      priceScore: 74,
      freshnessScore: 90,
      nutritionFitScore: 89,
      reasons: ["단백질 +12g 보강", "신선도 선호 반영"],
    },
  },
  {
    name: "방울토마토",
    quantity: "500g",
    priceKrw: 5500,
    reason: "파프리카 대체 (가격·신선도 우위)",
    delivery: "내일 도착(로켓프레시)",
    isAlternative: true,
    alternativeFor: "파프리카",
    score: {
      shoppingScore: 76,
      deliveryScore: 80,
      priceScore: 78,
      freshnessScore: 86,
      nutritionFitScore: 72,
      reasons: ["제철 채소", "저칼로리 곁들임"],
    },
  },
];

export function buildRunResponse(req: FridgeMateRequest): RunResponse {
  const ingredients =
    parseIngredients(req.ingredients).length > 0
      ? parseIngredients(req.ingredients)
      : parseIngredients(DEMO_REQUEST.ingredients);

  const proteinTarget = req.proteinTargetGram ?? 120;
  const calorieTarget = req.calorieTargetKcal ?? 1700;
  const budget = req.budgetKrw ?? 100000;

  const estimatedCost = SHOPPING_ITEMS.reduce((s, i) => s + i.priceKrw, 0);

  return {
    runId: uid("run"),
    mode: req.mode,
    ingredients,
    // (1) Pantry 분석
    pantry: {
      items: [
        { name: "닭가슴살", category: "단백질", freshness: "fresh", note: "냉장 보관 양호" },
        { name: "계란", category: "단백질", freshness: "fresh" },
        { name: "브로콜리", category: "채소", freshness: "urgent", expiryLabel: "D-2" },
        { name: "두부", category: "단백질(식물성)", freshness: "soon", expiryLabel: "D-1" },
      ],
      priorityUse: ["두부", "브로콜리"],
      summary: "유통기한이 가까운 두부와 브로콜리를 먼저 사용하는 식단으로 구성했어요.",
    },
    // (2)(3) 레시피 3개 이상 + citation
    recipes: [
      {
        id: "rcp_1",
        title: "닭가슴살 두부 강된장 덮밥",
        description: "두부와 닭가슴살을 강된장에 볶아 현미밥에 올린 고단백 한 그릇.",
        cookMinutes: 18,
        servings: req.peopleCount ?? 2,
        tags: ["고단백", "저탄수", "20분 이내"],
        mainIngredients: ["닭가슴살", "두부", "양파"],
        citations: [
          { label: "식품의약품안전처 식품영양성분DB", sourceId: "mfds-food-db", url: "https://various.foodsafetykorea.go.kr" },
        ],
        score: {
          baseScore: 0.81,
          seasonalBonus: 0.06,
          trendBonus: 0.04,
          finalScore: 0.91,
          reasons: ["임박 재료(두부) 우선 사용", "고단백 목표 적합", "조리 20분 이내"],
        },
      },
      {
        id: "rcp_2",
        title: "브로콜리 계란 스크램블",
        description: "임박한 브로콜리를 활용한 저탄수 단백질 반찬.",
        cookMinutes: 12,
        servings: req.peopleCount ?? 2,
        tags: ["저탄수", "채소"],
        mainIngredients: ["브로콜리", "계란"],
        citations: [
          { label: "농촌진흥청 표준 레시피", sourceId: "rda-recipe", url: "https://www.rda.go.kr" },
        ],
        score: {
          baseScore: 0.77,
          seasonalBonus: 0.05,
          trendBonus: 0.02,
          finalScore: 0.84,
          reasons: ["임박 재료(브로콜리) 우선 사용", "조리 시간 짧음"],
        },
      },
      {
        id: "rcp_3",
        title: "닭가슴살 두부 스테이크",
        description: "두부를 패티로 활용한 해산물 제외 고단백 스테이크.",
        cookMinutes: 20,
        servings: req.peopleCount ?? 2,
        tags: ["고단백", "해산물 제외"],
        mainIngredients: ["닭가슴살", "두부"],
        citations: [
          { label: "식품의약품안전처 식품영양성분DB", sourceId: "mfds-food-db" },
        ],
        score: {
          baseScore: 0.74,
          seasonalBonus: 0.03,
          trendBonus: 0.05,
          finalScore: 0.82,
          reasons: ["제외 재료(해산물) 미포함", "트렌드 상승 레시피"],
        },
      },
    ],
    // 식단 플랜 (3일 meal prep 형태, 임박 재료 우선)
    mealPlan: {
      note: "임박 재료를 앞쪽 일자에 배치했어요.",
      days: [
        {
          label: "1일차",
          entries: [
            { slot: "아침", recipeTitle: "브로콜리 계란 스크램블", usesPriorityItem: true },
            { slot: "점심", recipeTitle: "닭가슴살 두부 강된장 덮밥", usesPriorityItem: true },
            { slot: "저녁", recipeTitle: "닭가슴살 두부 스테이크", usesPriorityItem: true },
          ],
        },
        {
          label: "2일차",
          entries: [
            { slot: "아침", recipeTitle: "그릭요거트 + 방울토마토" },
            { slot: "점심", recipeTitle: "닭가슴살 두부 강된장 덮밥" },
            { slot: "저녁", recipeTitle: "브로콜리 계란 스크램블" },
          ],
        },
        {
          label: "3일차",
          entries: [
            { slot: "아침", recipeTitle: "계란 현미 주먹밥" },
            { slot: "점심", recipeTitle: "닭가슴살 두부 스테이크" },
            { slot: "저녁", recipeTitle: "닭가슴살 채소 볶음" },
          ],
        },
      ],
    },
    // (4) 영양 검증 PASS/보완
    nutrition: {
      protein: { current: 124, target: proteinTarget, unit: "g" },
      calories: { current: 1660, target: calorieTarget, unit: "kcal" },
      carbs: { current: 132, target: 150, unit: "g" },
      fat: { current: 48, target: 55, unit: "g" },
      passed: true,
      message: "단백질·칼로리 목표를 충족했어요. 탄수화물은 목표 범위 안에서 여유가 있어요.",
      warnings: ["지방이 목표 대비 다소 낮아요. 견과류를 소량 추가하면 균형이 좋아져요."],
    },
    // (5)(6)(7) 부족 재료 3개 이상 + 비용 + 쿠팡 URL + (8) 상품 점수
    shopping: {
      items: SHOPPING_ITEMS,
      estimatedCostKrw: estimatedCost,
      budgetKrw: budget,
      withinBudget: estimatedCost <= budget,
      coupangSearchUrl: COUPANG_SEARCH(SHOPPING_ITEMS.map((i) => i.name)),
      coupangCartUrl: undefined,
    },
    // (10) Agent Pipeline 5개
    pipeline: [
      {
        id: "pantry",
        order: 1,
        name: "Pantry Agent",
        status: "completed",
        message: "재료 분석 완료",
        logs: ["재료 4종 정규화", "임박 재료 2종 식별(두부 D-1, 브로콜리 D-2)"],
      },
      {
        id: "recipe",
        order: 2,
        name: "Recipe Agent",
        status: "completed",
        message: "레시피 후보 검색 완료",
        logs: ["RAG 후보 12건 검색", "제철·트렌드 보너스 반영 후 3건 선정"],
      },
      {
        id: "meal",
        order: 3,
        name: "Meal Agent",
        status: "running",
        message: "영양 목표 검증 중",
        logs: ["nutrition_calc 호출", "단백질 124/120g, 칼로리 1660/1700kcal"],
      },
      {
        id: "shopping",
        order: 4,
        name: "Shopping Agent",
        status: "pending",
        message: "부족 재료 계산 중",
        logs: ["budget_alloc 대기"],
      },
      {
        id: "executor",
        order: 5,
        name: "Executor Agent",
        status: "pending",
        message: "쿠팡 장바구니 준비 대기",
        logs: [],
      },
    ],
    warnings:
      req.excludedIngredients && req.excludedIngredients.includes("해산물")
        ? ["제외 재료(해산물)를 식단에서 제외했어요."]
        : [],
  };
}

export function buildCartResponse(
  items: ShoppingItem[],
  runId?: string,
): CartResponse {
  const used = items && items.length > 0 ? items : SHOPPING_ITEMS;
  const cartId = uid("cart");
  const names = used.map((i) => i.name);
  return {
    cartId,
    // 실제 자동 담기/결제는 구현하지 않음. 검색/담기로 이어지는 링크만 제공.
    coupangCartUrl: `https://www.coupang.com/np/search?q=${names
      .map((n) => encodeURIComponent(n))
      .join("%20")}&channel=fridgemate&cart=${cartId}`,
    coupangSearchUrl: COUPANG_SEARCH(names),
    items: used,
    estimatedCostKrw: used.reduce((s, i) => s + i.priceKrw, 0),
    message: "쿠팡 검색/장바구니 링크가 준비되었어요. (mock)",
  };
}
