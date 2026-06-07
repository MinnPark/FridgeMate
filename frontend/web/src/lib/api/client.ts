// FridgeMate AI - API 클라이언트 어댑터 (역할 D 핵심)
//
// 컴포넌트는 runPipeline() / createCart() 만 호출한다. mock/real 분기, base URL,
// 실패 시 mock fallback, 에러 정리는 이 계층이 책임진다.
//
// 팀 백엔드는 `POST /chat` (LangGraph, snake_case state) 를 쓴다.
// 프론트 contract(camelCase)와 다르므로 chatAdapter 의 매퍼로 변환한다.
//
// 환경변수:
//   NEXT_PUBLIC_USE_MOCK_API = "true" | "false"   (기본 true → mock)
//   NEXT_PUBLIC_API_BASE_URL = "http://localhost:8000"
//   NEXT_PUBLIC_API_FALLBACK_TO_MOCK = "true" | "false"  (real 실패 시 mock, 기본 true)

import {
  mapChatToRunResponse,
  mapRequestToChat,
  type ChatState,
} from "./chatAdapter";
import { buildCartResponse, buildRunResponse } from "./mock";
import type {
  CartRequest,
  CartResponse,
  CoupangSearchCandidate,
  DeliveryPreference,
  FridgeMateRequest,
  ProductRankResponse,
  RunResponse,
} from "./types";

const BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
const REQUEST_TIMEOUT_MS = 120_000;

function envFlag(value: string | undefined): boolean | undefined {
  if (value === undefined) return undefined;
  return value.toLowerCase() === "true";
}

/** mock 모드 여부. USE_MOCK_API 우선, 없으면 구버전 API_MODE, 기본은 mock. */
export function isMockMode(): boolean {
  const useMock = envFlag(process.env.NEXT_PUBLIC_USE_MOCK_API);
  if (useMock !== undefined) return useMock;
  const legacy = process.env.NEXT_PUBLIC_API_MODE;
  if (legacy) return legacy.toLowerCase() !== "real";
  return true; // 기본값: mock
}

export function getApiMode(): "mock" | "real" {
  return isMockMode() ? "mock" : "real";
}

function fallbackToMockEnabled(): boolean {
  return envFlag(process.env.NEXT_PUBLIC_API_FALLBACK_TO_MOCK) ?? true;
}

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/** 결과 + 어떤 경로로 받았는지(source) + 사용자용 안내(notice). */
export interface ApiResult<T> {
  data: T;
  source: "mock" | "real" | "fallback-mock";
  notice?: string;
}

async function postJson<T>(path: string, body: unknown): Promise<T> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  try {
    const res = await fetch(`${BASE_URL}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      cache: "no-store",
      signal: controller.signal,
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return (await res.json()) as T;
  } finally {
    clearTimeout(timeout);
  }
}

function friendlyError(prefix: string): string {
  return `${prefix} 백엔드에 연결하지 못했어요. 서버 실행 상태를 확인해 주세요.`;
}

/** 냉장고 재료 입력 → End-to-End 결과. real 모드는 팀 백엔드 `/chat` 호출 후 변환. */
export async function runPipeline(
  req: FridgeMateRequest,
): Promise<ApiResult<RunResponse>> {
  if (isMockMode()) {
    await delay(800);
    return { data: buildRunResponse(req), source: "mock" };
  }
  try {
    // 구조화 입력 → message/budget_limit 로 변환해 /chat 호출
    const state = await postJson<ChatState>("/chat", mapRequestToChat(req));
    // snake_case state → camelCase RunResponse 로 변환
    return { data: mapChatToRunResponse(state, req), source: "real" };
  } catch (err) {
    if (fallbackToMockEnabled()) {
      const data = buildRunResponse(req);
      return {
        data: { ...data, notice: "백엔드(/chat) 연결 실패로 mock 결과를 표시 중이에요." },
        source: "fallback-mock",
        notice: "실제 API 연결 실패 → mock fallback",
      };
    }
    throw new Error(friendlyError("분석 실행 실패:"));
  }
}

/**
 * 부족 재료 → 쿠팡 링크. (현재 팀 백엔드에 /api/cart 가 없으므로 real 모드에선
 * 실패 → mock fallback. 화면 핵심 흐름은 shopping.coupangSearchUrl 로 충분.)
 */
export async function createCart(
  req: CartRequest,
): Promise<ApiResult<CartResponse>> {
  if (isMockMode()) {
    await delay(500);
    return { data: buildCartResponse(req.items, req.runId), source: "mock" };
  }
  try {
    const data = await postJson<CartResponse>("/api/cart", req);
    return { data, source: "real" };
  } catch (err) {
    if (fallbackToMockEnabled()) {
      return {
        data: buildCartResponse(req.items, req.runId),
        source: "fallback-mock",
        notice: "백엔드 미제공 → mock fallback",
      };
    }
    throw new Error(friendlyError("장바구니 생성 실패:"));
  }
}

/** 백엔드 헬스 체크 (real 모드 연결 확인용). */
export async function checkHealth(): Promise<boolean> {
  if (isMockMode()) return true;
  try {
    const res = await fetch(`${BASE_URL}/health`, { cache: "no-store" });
    return res.ok;
  } catch {
    return false;
  }
}

export async function rankProductCandidates(input: {
  ingredient: string;
  neededAmount?: number;
  neededUnit?: "g" | "ml" | "개";
  preference?: DeliveryPreference;
  recipeContexts?: string[];
  candidates: CoupangSearchCandidate[];
}): Promise<ProductRankResponse> {
  return postJson<ProductRankResponse>("/shopping/rank-products", {
    ingredient: input.ingredient,
    needed_amount: input.neededAmount ?? null,
    needed_unit: input.neededUnit ?? null,
    preference: input.preference ?? "price",
    recipe_contexts: input.recipeContexts ?? [],
    candidates: input.candidates.slice(0, 5),
  });
}
