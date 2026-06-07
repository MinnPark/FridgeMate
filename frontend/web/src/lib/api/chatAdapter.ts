// FridgeMate AI - 백엔드 `/chat` ↔ 프론트 contract 변환기 (역할 D)
//
// 팀 백엔드(LangGraph)는 `POST /chat` 에 자연어 message 를 받아 LangGraph state(snake_case)를
// 통째로 돌려준다. 프론트는 구조화 입력 + camelCase RunResponse 를 기대한다.
// 이 파일이 그 차이를 흡수한다. (UI 컴포넌트는 안 건드림)
//
// 원칙: 백엔드가 안 주는 값은 임의로 만들어내지 않는다. optional 로 비우거나
//       notProvided/notice 로 "미제공/연동 대기"를 표시한다.

import type {
  AgentPipelineItem,
  FreshnessLevel,
  FridgeMateRequest,
  NutritionVerification,
  PantryItem,
  Recipe,
  RunResponse,
  ShoppingItem,
} from "./types";

// ── 백엔드 /chat 의 응답(LangGraph state) 모양 (snake_case) ───────────────────
export interface ChatRequest {
  message: string;
  budget_limit?: number | null;
  protein_target_gram?: number | null;
  calorie_target_kcal?: number | null;
  carbs_target_gram?: number | null;
  fat_target_gram?: number | null;
  ingredient_entries?: {
    name: string;
    amount: string;
    expiration_date: string; // "YYYY-MM-DD"
    storage_type: string;
  }[];
}

interface BackendPantryItem {
  name: string;
  amount?: number;
  unit?: string;
  expiry_priority?: "high" | "normal";
}
interface BackendRecipe {
  id: string;
  name: string;
  text?: string;
  ingredients?: { name: string; amount?: number; unit?: string }[];
  nutrition?: { calories?: number; protein?: number; carbs?: number; fat?: number };
}
interface BackendMeal {
  slot: string;
  name: string;
  reason?: string;
}
interface BackendLog {
  node?: string;
  event?: string;
  result?: Record<string, unknown>;
  [key: string]: unknown;
}
interface BackendPantryAnalysisItem {
  name: string;
  category?: string;
  freshness?: FreshnessLevel;
  amount?: string | null;
  expiry_label?: string | null;
  note?: string | null;
}

// 새 meal_agent 출력 형식 (entries 기반)
interface BackendMealEntry {
  slot: string;           // 이미 한국어: "아침" | "점심" | "저녁"
  recipeTitle: string;
  usesPriorityItem?: boolean;
}

// ── 상태 정의: 백엔드 응답(LangGraph state) 모양 (snake_case) ─────────────────
export interface ChatState {
  user_input?: string;
  budget_limit?: number | null;
  pantry_items?: BackendPantryItem[];
  pantry_analysis?: {
    items?: BackendPantryAnalysisItem[];
    priority_use?: string[];
    summary?: string;
  };

  // 새 meal_agent 출력 형식 (label/entries/note 기반)
  meal_plan?: {
    note?: string;                          // "임박 재료를 앞쪽 일자에 배치했어요."
    days?: {
      label?: string;                       // "1일차" | "2일차" | "3일차"
      entries?: BackendMealEntry[];         // 새 형식
      // ── 구 형식 fallback (이전 meal_agent 호환) ──
      day?: string;                         // "mon" | "tue" | ...
      meals?: BackendMeal[];
    }[];
    // 구 형식 fallback
    strategy?: string;
    pantry_used_first?: string[];
  };

  selected_recipes?: BackendRecipe[];
  recipe_search_trace?: { strategy?: string; original_query?: string };

  // 새 nutrition_tools.py 출력 형식
  nutrition_result?: {
    protein?:  { current?: number; target?: number; unit?: string };
    calories?: { current?: number; target?: number; unit?: string };
    carbs?:    { current?: number; target?: number; unit?: string };
    fat?:      { current?: number; target?: number; unit?: string };
    passed?:   boolean;
    message?:  string;
    warnings?: string[];
  };

  missing_ingredients?: {
    name: string;
    amount?: number | null;
    unit?: string | null;
    needed_by?: string[];
  }[];
  cart_items?: {
    ingredient: string;
    product_name?: string;
    quantity?: string;
    price?: number;
    deeplink?: string;
  }[];
  logs?: BackendLog[];
  final_response?: string;
}

// ── 요청 매퍼: 구조화 입력 → { message, budget_limit } ───────────────────────
export function mapRequestToChat(req: FridgeMateRequest): ChatRequest {
  const names = req.ingredients.trim();
  const goal = req.goal?.trim();

  // 구조화된 조건들을 자연어로 변환
  // ⚠️ "레시피/요리" 단어 금지 — supervisor 가 recipe 노드로만 라우팅됨
  const conditions: string[] = [];
  if (req.peopleCount)         conditions.push(`${req.peopleCount}인분`);
  if (req.maxCookingMinutes)   conditions.push(`조리 ${req.maxCookingMinutes}분 이내`);
  if (req.calorieTargetKcal)   conditions.push(`칼로리 ${req.calorieTargetKcal}kcal`);
  if (req.proteinTargetGram)   conditions.push(`단백질 ${req.proteinTargetGram}g`);
  if (req.excludedIngredients) conditions.push(`${req.excludedIngredients} 제외`);
  if (req.deliveryPreference)  conditions.push(`배송 ${req.deliveryPreference}`);
  if (req.mode && req.mode !== "today") conditions.push(`${req.mode} 모드`);

  const condStr = conditions.length > 0 ? ` ${conditions.join(", ")}.` : "";
  const message = `냉장고에 ${names} 있어.${goal ? ` ${goal}.` : ""}${condStr} 식단 짜줘`;

  return {
    message,
    budget_limit: req.budgetKrw ?? null,
    protein_target_gram: req.proteinTargetGram ?? null,
    calorie_target_kcal: req.calorieTargetKcal ?? null,
    ingredient_entries: req.ingredientEntries?.map((e) => ({
      name: e.name,
      amount: e.amount,
      expiration_date: e.expirationDate,
      storage_type: e.storageType,
    })),
  };
}

// ── 응답 매퍼: ChatState(snake) → RunResponse(camel) ────────────────────────
const SLOT_KO: Record<string, string> = {
  breakfast: "아침",
  lunch: "점심",
  dinner: "저녁",
};
const DAY_KO: Record<string, string> = {
  mon: "월요일",
  tue: "화요일",
  wed: "수요일",
  thu: "목요일",
  fri: "금요일",
  sat: "토요일",
  sun: "일요일",
};

function coupangSearch(names: string[]): string {
  const first = names.find((name) => name.trim());
  return first
    ? `https://www.coupang.com/np/search?q=${encodeURIComponent(first)}`
    : "https://www.coupang.com/";
}

function formatMissingQuantity(
  amount?: number | null,
  unit?: string | null,
): string {
  if (amount === undefined || amount === null) return unit || "수량 확인 필요";
  const rounded = Math.round(amount * 100) / 100;
  const value = Number.isInteger(rounded)
    ? String(rounded)
    : rounded.toFixed(2).replace(/0+$/, "").replace(/\.$/, "");
  return `${value}${unit ?? ""}`;
}

// 개수로 사는 과일류(무게→개 환산 대상). 무게/팩으로 파는 베리류(딸기·포도·블루베리 등)는 제외.
const FRUITS = new Set([
  "사과", "배", "바나나", "귤", "오렌지", "감", "단감", "홍시", "복숭아", "천도복숭아",
  "자두", "키위", "레몬", "라임", "자몽", "망고", "참외", "멜론", "수박", "파인애플",
  "석류", "아보카도", "살구", "한라봉", "천혜향", "유자", "모과", "무화과", "파파야",
]);

function mapMissingToShoppingItems(
  missing: NonNullable<ChatState["missing_ingredients"]>,
): ShoppingItem[] {
  const grouped = new Map<
    string,
    { quantities: string[]; neededBy: Set<string>; totalG: number; totalMl: number }
  >();

  for (const item of missing) {
    const name = item.name.trim();
    if (!name) continue;
    const current = grouped.get(name) ?? {
      quantities: [],
      neededBy: new Set<string>(),
      totalG: 0,
      totalMl: 0,
    };
    const quantity = formatMissingQuantity(item.amount, item.unit);
    if (!current.quantities.includes(quantity)) current.quantities.push(quantity);
    // 필요 총량: 무게(g)·부피(ml) 계열만 합산.
    //  - g/kg → g, ml/l → ml, 컵 → ml(계량컵 200ml)
    //  - 큰술/작은술/개 등은 수량 매칭 제외 → 1개 담기(최소).
    const unit = String(item.unit ?? "").toLowerCase().trim();
    const a = item.amount;
    if (typeof a === "number" && Number.isFinite(a)) {
      if (unit === "g" || unit === "그램") current.totalG += Math.round(a);
      else if (unit === "kg" || unit === "킬로") current.totalG += Math.round(a * 1000);
      else if (unit === "ml") current.totalMl += Math.round(a);
      else if (unit === "l" || unit === "리터") current.totalMl += Math.round(a * 1000);
      else if (unit === "컵") current.totalMl += Math.round(a * 200);
    }
    for (const recipe of item.needed_by ?? []) current.neededBy.add(recipe);
    grouped.set(name, current);
  }

  return Array.from(grouped, ([name, value]) => {
    // 한 재료에 무게·부피가 섞이면 무게(g)를 우선.
    let neededAmount: number | undefined =
      value.totalG > 0 ? value.totalG : value.totalMl > 0 ? value.totalMl : undefined;
    let neededUnit: "g" | "ml" | "개" | undefined =
      value.totalG > 0 ? "g" : value.totalMl > 0 ? "ml" : undefined;
    // 과일류: 무게가 잡히면 개수로 환산(일괄 200g/개, 200g 미만이면 1개).
    //  g로 검색하면 사과칩·말랭이 등 가공품이 떠서, 개 단위는 이름만으로 검색하게 한다.
    if (FRUITS.has(name) && value.totalG > 0) {
      neededAmount = Math.max(1, Math.ceil(value.totalG / 200));
      neededUnit = "개";
    }
    return {
      name,
      quantity: value.quantities.join(" + "),
      priceKrw: 0,
      neededAmount,
      neededUnit,
      reason:
        value.neededBy.size > 0
          ? `필요 식단: ${Array.from(value.neededBy).join(", ")}`
          : "식단에 필요한 부족 재료",
    };
  });
}

export function mapChatToRunResponse(
  state: ChatState,
  req: FridgeMateRequest,
): RunResponse {
  const pantryRaw = state.pantry_items ?? [];

  // 새 Pantry Agent의 pantry_analysis가 있으면 그것을 우선 사용(snake→camel),
  // 없으면 기존 pantry_items 기반으로 fallback.
  const pa = state.pantry_analysis;
  const usePa = Boolean(pa?.items && pa.items.length > 0);

  const priorityUse = usePa
    ? pa!.priority_use ?? []
    : pantryRaw.filter((p) => p.expiry_priority === "high").map((p) => p.name);

  const pantryItems: PantryItem[] = usePa
    ? pa!.items!.map((it) => ({
        name: it.name,
        category: it.category ?? "재료",
        freshness: it.freshness ?? "fresh",
        amount: it.amount ?? undefined,
        expiryLabel: it.expiry_label ?? undefined, // 예: "3일 남음"
        note: it.note ?? undefined, // 보관방법(예: "냉장 보관")
      }))
    : pantryRaw.map((p) => ({
        name: p.name,
        category: "재료", // 백엔드 미제공 → 일반 라벨
        freshness: p.expiry_priority === "high" ? "soon" : "fresh",
        amount: p.amount !== undefined ? `${p.amount}${p.unit ?? ""}` : undefined,
      }));

  const pantrySummary = usePa
    ? pa!.summary ?? "입력한 재료를 분석했어요."
    : priorityUse.length > 0
      ? "유통기한이 가까운 재료를 우선 사용하는 식단이에요."
      : "입력한 재료를 우선 사용하도록 구성했어요.";

  // 레시피 (중복 id 제거)
  const seen = new Set<string>();
  const strategy = state.recipe_search_trace?.strategy;
  const recipes: Recipe[] = (state.selected_recipes ?? [])
    .filter((r) => (seen.has(r.id) ? false : (seen.add(r.id), true)))
    .map((r) => ({
      id: r.id,
      title: r.name,
      description: r.text ?? "",
      // cookMinutes/servings/tags/score 는 백엔드 미제공 → 비움
      servings: req.peopleCount, // 사용자가 입력한 값(백엔드 데이터 아님)
      tags: [],
      mainIngredients: (r.ingredients ?? []).map((i) => i.name),
      citations: [
        {
          label: `RAG${strategy ? ` · ${strategy}` : ""} (백엔드 mock index)`,
          sourceId: "backend-rag",
        },
      ],
    }));

  // ── 식단 ────────────────────────────────────────────────────────────────────
  // 새 형식(label/entries) 우선, 구 형식(day/meals) fallback
  const mealDays = (state.meal_plan?.days ?? []).map((d) => {
    const isNewFormat = Boolean(d.label || d.entries);

    if (isNewFormat) {
      // 새 meal_agent 형식: label/entries/recipeTitle/usesPriorityItem
      return {
        label: d.label ?? "—",
        entries: (d.entries ?? []).map((e) => ({
          slot: e.slot,                          // 이미 한국어 ("아침"/"점심"/"저녁")
          recipeTitle: e.recipeTitle,
          usesPriorityItem: e.usesPriorityItem ?? false,  // 백엔드 값 직접 사용
        })),
      };
    }

    // 구 meal_agent 형식 fallback: day/meals/name
    return {
      label: DAY_KO[d.day ?? ""] ?? d.day ?? "—",
      entries: (d.meals ?? []).map((m) => ({
        slot: SLOT_KO[m.slot] ?? m.slot,
        recipeTitle: m.name,
        usesPriorityItem: priorityUse.some((n) => m.name.includes(n)),
      })),
    };
  });

  // ── 영양 ────────────────────────────────────────────────────────────────────
  // state.nutrition_result 우선 (새 nutrition_tools.py 형식)
  // fallback: logs의 nutrition_verified 결과 (구 형식)
  const nr = state.nutrition_result;

  const nutrition: NutritionVerification = nr
    ? {
        // 새 형식: nutrition_result 직접 매핑
        protein: {
          current: nr.protein?.current ?? 0,
          target:  nr.protein?.target  ?? req.proteinTargetGram ?? 0,
          unit:    nr.protein?.unit    ?? "g",
        },
        calories: {
          current: nr.calories?.current ?? 0,
          target:  nr.calories?.target  ?? req.calorieTargetKcal ?? 0,
          unit:    nr.calories?.unit    ?? "kcal",
        },
        carbs: nr.carbs
          ? { current: nr.carbs.current ?? 0, target: nr.carbs.target ?? 0, unit: "g" }
          : undefined,
        fat: nr.fat
          ? { current: nr.fat.current ?? 0, target: nr.fat.target ?? 0, unit: "g" }
          : undefined,
        passed:   nr.passed  ?? false,
        message:  nr.message ?? (nr.passed ? "영양 목표를 충족했어요." : "영양 목표에 미달했어요."),
        warnings: nr.warnings ?? [],
      }
    : (() => {
        // 구 형식 fallback: logs에서 nutrition_verified 결과 추출
        const nc = (state.logs ?? []).find((l) => l.event === "nutrition_verified")
          ?.result as
          | { total?: { calories?: number; protein?: number }; goal?: { protein_min?: number }; passed?: boolean }
          | undefined;

        const passed = nc?.passed ?? false;
        return {
          protein: {
            current: nc?.total?.protein ?? 0,
            target:  nc?.goal?.protein_min ?? req.proteinTargetGram ?? 0,
            unit:    "g",
          },
          calories: {
            current: nc?.total?.calories ?? 0,
            target:  req.calorieTargetKcal ?? 0,
            unit:    "kcal",
          },
          passed,
          message: passed
            ? "단백질 목표를 충족했어요. (백엔드 영양 검증 결과)"
            : "단백질 목표에 미달했어요. 보완이 필요합니다. (백엔드 영양 검증 결과)",
          notProvided: ["탄수화물", "지방", req.calorieTargetKcal ? "" : "칼로리 목표"]
            .filter(Boolean) as string[],
        };
      })();

  // 장보기
  // 새 Shopping Agent는 역할 분리에 따라 missing_ingredients만 계산한다.
  // 구형 백엔드의 cart_items도 계속 호환하되, 새 계약을 우선 사용한다.
  const missing = state.missing_ingredients ?? [];
  const carts = state.cart_items ?? [];
  const shoppingItems: ShoppingItem[] =
    missing.length > 0
      ? mapMissingToShoppingItems(missing)
      : carts.map((c) => ({
          name: c.ingredient,
          quantity: c.quantity ?? "-",
          priceKrw: c.price ?? 0,
          reason: c.product_name,
          // 구형 백엔드는 검색 deeplink만 제공하므로 productUrl은 비운다.
        }));
  const estimated = shoppingItems.reduce((s, i) => s + i.priceKrw, 0);
  const budget = state.budget_limit ?? req.budgetKrw ?? undefined;
  const withinBudget = budget !== undefined ? estimated <= budget : true;

  // Agent Pipeline: logs/route 기반 최소 상태만
  const has = (v: unknown[] | undefined) => Boolean(v && v.length);
  const logEvents = (node: string) =>
    (state.logs ?? [])
      .filter((l) => l.node === node && l.event)
      .map((l) => String(l.event));

  const pipeline: AgentPipelineItem[] = [
    {
      id: "pantry",
      order: 1,
      name: "Pantry Agent",
      status: pantryItems.length > 0 ? "completed" : "pending",
      message: pantryItems.length > 0 ? "재료 분석 완료" : "재료 분석 대기",
      logs: logEvents("pantry"),
    },
    {
      id: "recipe",
      order: 2,
      name: "Recipe Agent",
      status: has(recipes) ? "completed" : "pending",
      message: has(recipes) ? `레시피 ${recipes.length}건 검색 완료` : "레시피 검색 대기",
      logs: strategy ? [`RAG 전략: ${strategy}`] : logEvents("recipe"),
    },
    {
      id: "meal",
      order: 3,
      name: "Meal Agent",
      status: state.meal_plan ? "completed" : "pending",
      message: state.meal_plan ? "식단/영양 검증 완료" : "식단 계획 대기",
      logs: logEvents("meal"),
    },
    {
      id: "shopping",
      order: 4,
      name: "Shopping Agent",
      status:
        state.logs?.some(
          (log) => log.node === "shopping" && log.event === "missing_calculated",
        ) || has(carts)
          ? "completed"
          : "pending",
      message:
        state.logs?.some(
          (log) => log.node === "shopping" && log.event === "missing_calculated",
        ) || has(carts)
          ? `부족 재료 ${shoppingItems.length}개 계산 완료`
          : "부족 재료 계산 대기",
      logs: logEvents("shopping"),
    },
    {
      id: "executor",
      order: 5,
      name: "Executor Agent",
      status: "pending",
      message: "쿠팡 자동 담기 대기 (Chrome 확장 · 백엔드 미연동)",
      logs: [],
    },
  ];

  const warnings: string[] = [];
  if (!withinBudget) warnings.push("예산을 초과했습니다. 사용자 승인이 필요합니다.");

  return {
    runId: `chat_${Date.now()}`,
    mode: req.mode,
    ingredients: pantryItems.map((p) => p.name),
    pantry: {
      items: pantryItems,
      priorityUse,
      summary: pantrySummary,
    },
    recipes,
    mealPlan: {
      days: mealDays,
      // 새 형식: meal_plan.note 우선, 구 형식: strategy fallback
      note: state.meal_plan?.note
        ?? (state.meal_plan?.strategy ? `전략: ${state.meal_plan.strategy}` : undefined),
    },
    nutrition,
    shopping: {
      items: shoppingItems,
      estimatedCostKrw: estimated,
      budgetKrw: budget,
      withinBudget,
      coupangSearchUrl: coupangSearch(shoppingItems.map((i) => i.name)),
    },
    pipeline,
    warnings,
    notice:
      "실제 백엔드(/chat) 응답을 변환해 표시 중입니다. 부족 재료의 가격과 상품 URL은 Chrome Extension 검색 후 확정됩니다.",
  };
}
