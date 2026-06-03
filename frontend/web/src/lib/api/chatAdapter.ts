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
  [k: string]: unknown;
}
export interface ChatState {
  user_input?: string;
  budget_limit?: number | null;
  pantry_items?: BackendPantryItem[];
  meal_plan?: {
    strategy?: string;
    days?: { day?: string; meals?: BackendMeal[] }[];
    pantry_used_first?: string[];
  };
  selected_recipes?: BackendRecipe[];
  recipe_search_trace?: { strategy?: string; original_query?: string };
  missing_ingredients?: { name: string; amount?: number; unit?: string }[];
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
  // 백엔드 supervisor 는 "레시피/요리" 단어가 있으면 recipe 노드로만 가므로 제외(전체 흐름=meal).
  const message = `냉장고에 ${names} 있어.${goal ? ` ${goal}` : ""} 식단 짜줘`;
  return { message, budget_limit: req.budgetKrw ?? null };
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
  return (
    "https://www.coupang.com/np/search?q=" +
    names.map((n) => encodeURIComponent(n)).join("%20")
  );
}

export function mapChatToRunResponse(
  state: ChatState,
  req: FridgeMateRequest,
): RunResponse {
  const pantryRaw = state.pantry_items ?? [];
  const priorityUse = pantryRaw
    .filter((p) => p.expiry_priority === "high")
    .map((p) => p.name);

  const pantryItems: PantryItem[] = pantryRaw.map((p) => ({
    name: p.name,
    category: "재료", // 백엔드 미제공 → 일반 라벨
    freshness: p.expiry_priority === "high" ? "soon" : "fresh",
    amount: p.amount !== undefined ? `${p.amount}${p.unit ?? ""}` : undefined,
  }));

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

  // 식단
  const mealDays = (state.meal_plan?.days ?? []).map((d) => ({
    label: DAY_KO[d.day ?? ""] ?? d.day ?? "—",
    entries: (d.meals ?? []).map((m) => ({
      slot: SLOT_KO[m.slot] ?? m.slot,
      recipeTitle: m.name,
      usesPriorityItem: priorityUse.some((n) => m.name.includes(n)),
    })),
  }));

  // 영양: logs 의 nutrition_verified 결과에서 추출
  const nc = (state.logs ?? []).find((l) => l.event === "nutrition_verified")
    ?.result as
    | { total?: { calories?: number; protein?: number }; goal?: { protein_min?: number }; passed?: boolean }
    | undefined;

  const proteinCur = nc?.total?.protein ?? 0;
  const proteinTgt = nc?.goal?.protein_min ?? req.proteinTargetGram ?? 0;
  const passed = nc?.passed ?? false;
  const nutrition: NutritionVerification = {
    protein: { current: proteinCur, target: proteinTgt, unit: "g" },
    calories: {
      current: nc?.total?.calories ?? 0,
      target: req.calorieTargetKcal ?? 0, // 백엔드 미제공 → 사용자 목표값(없으면 0)
      unit: "kcal",
    },
    // carbs/fat 는 백엔드 검증 결과에 없음 → 미제공
    passed,
    message: passed
      ? "단백질 목표를 충족했어요. (백엔드 영양 검증 결과)"
      : "단백질 목표에 미달했어요. 보완이 필요합니다. (백엔드 영양 검증 결과)",
    notProvided: ["탄수화물", "지방", req.calorieTargetKcal ? "" : "칼로리 목표"].filter(
      Boolean,
    ) as string[],
  };

  // 장보기 (cart_items 기반)
  const carts = state.cart_items ?? [];
  const shoppingItems: ShoppingItem[] = carts.map((c) => ({
    name: c.ingredient,
    quantity: c.quantity ?? "-",
    priceKrw: c.price ?? 0,
    reason: c.product_name,
    // productUrl 미제공(백엔드는 검색 deeplink만) → 자동 담기 시 skip / score·delivery 미제공
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
      status: has(pantryRaw) ? "completed" : "pending",
      message: has(pantryRaw) ? "재료 분석 완료" : "재료 분석 대기",
      logs: logEvents("meal").filter((e) => e.includes("plan")),
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
      status: has(carts) ? "completed" : "pending",
      message: has(carts) ? "부족 재료/장바구니 후보 생성 완료" : "부족 재료 계산 대기",
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
    ingredients: pantryRaw.map((p) => p.name),
    pantry: {
      items: pantryItems,
      priorityUse,
      summary:
        priorityUse.length > 0
          ? "유통기한이 가까운 재료를 우선 사용하는 식단이에요."
          : "입력한 재료를 우선 사용하도록 구성했어요.",
    },
    recipes,
    mealPlan: {
      days: mealDays,
      note: state.meal_plan?.strategy
        ? `전략: ${state.meal_plan.strategy}`
        : undefined,
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
      "실제 백엔드(/chat) 응답을 변환해 표시 중입니다. 일부 값(조리시간·태그·상품점수·상품URL·탄수/지방)은 백엔드 미제공이라 비어 있습니다.",
  };
}
