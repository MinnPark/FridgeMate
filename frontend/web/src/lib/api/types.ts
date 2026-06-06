// FridgeMate AI - API 타입 정의 (역할 D)
//
// 기획서 기반 계약(contract). 응답 점수/추론 값은 프론트엔드에서 계산하지 않고
// mock 또는 백엔드가 내려준다고 가정하고 "표시 가능한 구조"만 정의한다.
// 팀 백엔드(`POST /chat`, snake_case)와의 변환은 chatAdapter.ts 에서 처리한다.

// ---------------------------------------------------------------------------
// 요청(Request)
// ---------------------------------------------------------------------------
export type FridgeMateMode = "today" | "weekend" | "meal_prep" | "goal";

export type DeliveryPreference = "speed" | "freshness" | "price" | "nutrition";

export interface FridgeMateRequest {
  ingredients: string; // 쉼표 구분 텍스트 (예: "닭가슴살, 계란, 브로콜리, 두부")
  ingredientEntries?: IngredientEntry[]; // 재료 세부정보(용량/유통기한/보관) — 백엔드 Pantry 분석용
  mode: FridgeMateMode;
  goal?: string;
  proteinTargetGram?: number;
  calorieTargetKcal?: number;
  budgetKrw?: number;
  peopleCount?: number;
  excludedIngredients?: string;
  maxCookingMinutes?: number;
  deliveryPreference?: DeliveryPreference;
}

// ---------------------------------------------------------------------------
// 점수 정보 (제철·트렌드·상품 점수 등) — 표시 전용. 프론트에서 계산하지 않는다.
// ---------------------------------------------------------------------------
export interface ScoreInfo {
  // 레시피 점수 계열
  baseScore?: number; // RAG 기본 유사도
  seasonalBonus?: number; // 제철 보너스
  trendBonus?: number; // 트렌드 보너스
  finalScore?: number; // 최종 레시피 점수
  // 상품 점수 계열
  shoppingScore?: number;
  deliveryScore?: number;
  priceScore?: number;
  freshnessScore?: number;
  nutritionFitScore?: number;
  // 산정 이유 문구
  reasons?: string[];
}

// ---------------------------------------------------------------------------
// Agent Pipeline
// ---------------------------------------------------------------------------
export type AgentStatus = "completed" | "running" | "pending" | "failed";

export type AgentId = "pantry" | "recipe" | "meal" | "shopping" | "executor";

export interface AgentPipelineItem {
  id: AgentId;
  order: number;
  name: string;
  status: AgentStatus;
  message: string;
  logs?: string[];
}

// ---------------------------------------------------------------------------
// Pantry 분석
// ---------------------------------------------------------------------------
export type FreshnessLevel = "fresh" | "soon" | "urgent";

export interface PantryItem {
  name: string;
  category: string; // 단백질 / 채소 / 가공 ...
  freshness: FreshnessLevel;
  expiryLabel?: string; // "D-1" (수치 계산 아님, 라벨 표시용)
  note?: string;
  amount?: string; // 용량/수량 (예: "300g", "1모", "10개")
  expirationDate?: string; // 유통기한 (예: "2025-05-18")
  storageType?: string; // 보관 방법 (예: "냉장 보관")
}

// 사용자가 직접 입력한 재료(상세 입력 팝업에서 받음). Pantry 분석에 반영된다.
// 상세 입력 팝업에서 모두 필수로 받으므로 전 필드 필수(백엔드 ingredient_entries 계약과 일치).
export interface IngredientEntry {
  name: string;
  amount: string; // 용량/수량 (예: "300g", "1모", "10개")
  expirationDate: string; // 유통기한 "YYYY-MM-DD"
  storageType: string; // 보관 방법 (예: "냉장 보관")
}

export interface PantryAnalysis {
  items: PantryItem[];
  priorityUse: string[]; // 임박 재료 우선 사용 대상 이름들
  summary: string; // "유통기한이 가까운 재료를 우선 사용해요." 류
}

// ---------------------------------------------------------------------------
// 레시피 / 식단
// ---------------------------------------------------------------------------
export interface Citation {
  label: string; // "식품의약품안전처 식품DB"
  sourceId: string; // 내부 출처 식별자
  url?: string;
}

export interface Recipe {
  id: string;
  title: string;
  description: string;
  cookMinutes?: number; // 백엔드 미제공 가능 → optional
  servings?: number; // 백엔드 미제공 가능 → optional
  tags: string[]; // ["고단백", "저탄수"] 등 (없으면 빈 배열)
  mainIngredients: string[];
  citations: Citation[];
  score?: ScoreInfo;
}

export interface MealPlanEntry {
  slot: string; // 아침 / 점심 / 저녁
  recipeTitle: string;
  usesPriorityItem?: boolean; // 임박 재료 우선 사용 여부
}

export interface MealPlanDay {
  label: string; // "1일차" 등
  entries: MealPlanEntry[];
}

export interface MealPlan {
  days: MealPlanDay[];
  note?: string;
}

// ---------------------------------------------------------------------------
// 영양 검증
// ---------------------------------------------------------------------------
export interface NutrientMetric {
  current: number;
  target: number;
  unit: string;
}

export interface NutritionVerification {
  protein: NutrientMetric;
  calories: NutrientMetric;
  carbs?: NutrientMetric; // 백엔드 미제공 가능 → optional
  fat?: NutrientMetric; // 백엔드 미제공 가능 → optional
  passed: boolean; // 영양 목표 PASS 여부
  message: string; // PASS 또는 보완 안내
  warnings?: string[];
  notProvided?: string[]; // 백엔드 미제공 항목명(표시용, 예: "탄수화물", "지방")
}

// ---------------------------------------------------------------------------
// 장보기 / 실행부
// ---------------------------------------------------------------------------
export interface ShoppingItem {
  name: string;
  quantity: string; // "1kg", "2개 (400g)"
  priceKrw: number;
  reason?: string; // 추천 이유 문구
  delivery?: string; // 배송 조건 (예: "내일 도착(로켓배송)") — 표시 전용
  isAlternative?: boolean; // 대체재 여부 (Shopping Agent/백엔드 판단, 표시 전용)
  alternativeFor?: string; // 어떤 재료의 대체재인지
  productUrl?: string; // 쿠팡 상품 URL (자동 담기 대상, 없으면 skipped) — mock/API 제공
  score?: ScoreInfo; // 상품 점수 (mock/백엔드 제공)
}

export interface ShoppingList {
  items: ShoppingItem[];
  estimatedCostKrw: number;
  budgetKrw?: number;
  withinBudget: boolean;
  coupangSearchUrl: string;
  coupangCartUrl?: string;
}

// ---------------------------------------------------------------------------
// 응답(Response)
// ---------------------------------------------------------------------------
export interface RunResponse {
  runId: string;
  mode: FridgeMateMode;
  ingredients: string[];
  pantry: PantryAnalysis;
  recipes: Recipe[];
  mealPlan: MealPlan;
  nutrition: NutritionVerification;
  shopping: ShoppingList;
  pipeline: AgentPipelineItem[];
  warnings: string[];
  notice?: string; // 예: mock fallback 안내
}

export interface CartRequest {
  items: ShoppingItem[];
  runId?: string;
}

export interface CartResponse {
  cartId: string;
  coupangCartUrl: string;
  coupangSearchUrl: string;
  items: ShoppingItem[];
  estimatedCostKrw: number;
  message: string;
}

export interface HealthResponse {
  status: string;
  service: string;
  version: string;
}

// ---------------------------------------------------------------------------
// 쿠팡 장바구니 자동 담기 (Playwright 실행부)
// ---------------------------------------------------------------------------
export interface CartExecuteItem {
  ingredient: string;
  productUrl?: string;
  searchUrl?: string;
  quantity?: number;
  optionText?: string;
}

export interface CartExecuteRequest {
  items: CartExecuteItem[];
}

export type CartAddStatus = "success" | "failed" | "skipped";

export interface CartAddResult {
  itemName: string;
  productUrl?: string;
  status: CartAddStatus;
  message: string;
}

export interface CartExecuteResponse {
  executionMode: "playwright" | "extension";
  status: "completed" | "partial_failed" | "failed";
  results: CartAddResult[];
  message: string;
}
