"use client";

import { useCallback, useRef, useState } from "react";

import { AgentPipelinePanel } from "@/components/AgentPipelinePanel";
import { CartExecutionCard } from "@/components/CartExecutionCard";
import { ConditionBar } from "@/components/ConditionBar";
import { Header } from "@/components/Header";
import { InputPanel } from "@/components/InputPanel";
import { MealPlanCard } from "@/components/MealPlanCard";
import { NutritionCard } from "@/components/NutritionCard";
import { PantryCard } from "@/components/PantryCard";
import { PlaceholderCard } from "@/components/PlaceholderCard";
import { RecipesCard } from "@/components/RecipesCard";
import { runPipeline } from "@/lib/api/client";
import { DEFAULT_INGREDIENT_ENTRIES, DEMO_REQUEST } from "@/lib/api/mock";
import type {
  AgentId,
  AgentPipelineItem,
  AgentStatus,
  FridgeMateMode,
  FridgeMateRequest,
  IngredientEntry,
  RunResponse,
} from "@/lib/api/types";

function isValidRunResponse(d: RunResponse | undefined | null): d is RunResponse {
  return Boolean(
    d &&
      Array.isArray(d.pipeline) &&
      d.pipeline.length > 0 &&
      d.shopping &&
      Array.isArray(d.recipes),
  );
}

// 분석 전체 상태.
type RunStatus = "idle" | "running" | "completed" | "error";

// 파이프라인 단계(=Agent Pipeline 패널 + 카드 단계적 공개의 단일 소스). id 는 기존 AgentId.
const PIPELINE_STAGES: { id: AgentId; name: string }[] = [
  { id: "pantry", name: "Pantry Agent" },
  { id: "recipe", name: "Recipe Agent" },
  { id: "meal", name: "Meal Agent" },
  { id: "shopping", name: "Shopping Agent" },
  { id: "executor", name: "Executor Agent" },
];
// 단계별 공개 연출 간격(데이터는 한 번에 받지만 순서대로 노출).
const REVEAL_INTERVAL_MS = 700;

function delay(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms));
}

// 한 페이지 End-to-End 대시보드: 상단 헤더 / 좌(메인) · 우(Agent Pipeline) 2열.
// 레이아웃은 분석 전/중/완료 모두 동일하게 유지하고, 각 영역만 placeholder→결과로 채운다.
export default function HomePage() {
  const [ingredients, setIngredients] = useState<IngredientEntry[]>(
    DEFAULT_INGREDIENT_ENTRIES,
  );
  const [request, setRequest] = useState<FridgeMateRequest>(DEMO_REQUEST);
  const [result, setResult] = useState<RunResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [runStatus, setRunStatus] = useState<RunStatus>("idle");
  // 완료된 단계 수(0..PIPELINE_STAGES.length). 카드 공개·패널 상태를 결정.
  const [revealed, setRevealed] = useState(0);
  // 재실행 시 이전 실행의 지연 공개 루프를 무효화하기 위한 토큰.
  const runTokenRef = useRef(0);

  const run = useCallback(async () => {
    if (ingredients.length === 0) {
      setError("재료를 1개 이상 입력해 주세요.");
      return;
    }
    const token = ++runTokenRef.current;
    setError(null);
    setResult(null);
    setRevealed(0);
    setRunStatus("running");
    try {
      const req: FridgeMateRequest = {
        ...request,
        ingredients: ingredients.map((i) => i.name).join(", "),
        ingredientEntries: ingredients, // 세부정보(용량/유통기한/보관)도 함께 전달
      };
      const { data, notice } = await runPipeline(req);
      if (token !== runTokenRef.current) return; // 그새 재실행됨 → 폐기
      if (!isValidRunResponse(data)) {
        setRunStatus("error");
        setError("결과 형식이 올바르지 않아요. 잠시 후 다시 시도해 주세요.");
        return;
      }
      setResult(data);
      if (notice) setError("백엔드 연결에 실패했습니다. 현재는 예시 결과를 표시합니다.");
      // 파이프라인 순서대로 단계적으로 공개.
      for (let s = 1; s <= PIPELINE_STAGES.length; s++) {
        await delay(REVEAL_INTERVAL_MS);
        if (token !== runTokenRef.current) return;
        setRevealed(s);
      }
      setRunStatus("completed");
    } catch (e) {
      if (token !== runTokenRef.current) return;
      console.error(e);
      setRunStatus("error");
      setError("분석에 실패했습니다. 잠시 후 다시 시도해 주세요.");
    }
  }, [ingredients, request]);

  function addIngredient(entry: IngredientEntry) {
    setIngredients((prev) =>
      prev.some((i) => i.name === entry.name) ? prev : [...prev, entry],
    );
  }
  function removeIngredient(name: string) {
    setIngredients((prev) => prev.filter((i) => i.name !== name));
  }

  // 특정 단계(stageIndex)에 대응하는 영역의 placeholder 문구.
  function placeholderMessage(stageIndex: number): string {
    if (runStatus === "running") {
      if (revealed === stageIndex) return "분석 중입니다…";
      if (revealed < stageIndex) return "대기 중";
    }
    return "분석 전입니다";
  }
  // 해당 단계가 현재 진행 중인지.
  function isAnalyzing(stageIndex: number): boolean {
    return runStatus === "running" && revealed === stageIndex;
  }
  // 결과를 노출할지(해당 단계가 완료됐고 데이터가 있을 때).
  function revealedAt(stageIndex: number): boolean {
    return Boolean(result) && revealed > stageIndex;
  }

  // Agent Pipeline 패널용 데이터(프론트 단계 상태 기반, 완료 단계는 결과의 message/logs 사용).
  function buildPipeline(): AgentPipelineItem[] {
    return PIPELINE_STAGES.map((stage, i) => {
      let status: AgentStatus;
      if (i < revealed) status = "completed";
      else if (runStatus === "error" && i === revealed) status = "failed";
      else if (runStatus === "running" && i === revealed) status = "running";
      else status = "pending";

      const fromResult = result?.pipeline.find((p) => p.id === stage.id);
      const message =
        status === "completed"
          ? (fromResult?.message ?? "완료")
          : status === "running"
            ? "분석 중입니다…"
            : status === "failed"
              ? "분석 실패"
              : "대기 중";

      return {
        id: stage.id,
        order: i + 1,
        name: stage.name,
        status,
        message,
        logs: status === "completed" ? fromResult?.logs : undefined,
      };
    });
  }

  return (
    <div className="mx-auto flex h-screen max-w-[1600px] flex-col overflow-hidden">
      <Header />

      <main className="flex flex-1 gap-4 overflow-hidden px-4 pb-4">
        {/* 좌: 메인 대시보드 (레이아웃은 항상 동일, 영역만 placeholder→결과) */}
        <div className="flex min-w-0 flex-1 flex-col gap-3 overflow-y-auto pr-1">
          <InputPanel
            ingredients={ingredients}
            onAddIngredient={addIngredient}
            onRemoveIngredient={removeIngredient}
            mode={request.mode}
            onModeChange={(m: FridgeMateMode) =>
              setRequest((r) => ({ ...r, mode: m }))
            }
            onRun={run}
            loading={runStatus === "running"}
          />

          <ConditionBar value={request} onChange={setRequest} />

          {error && (
            <div className="rounded-xl border border-amber-400/30 bg-amber-400/10 px-4 py-2 text-sm text-amber-200">
              {error}
            </div>
          )}

          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            {/* Pantry (단계 0) */}
            {revealedAt(0) ? (
              <div className="animate-reveal h-full [&>section]:h-full">
                <PantryCard pantry={result!.pantry} ingredients={ingredients} />
              </div>
            ) : (
              <PlaceholderCard
                icon="🧺"
                title="Pantry 분석"
                message={placeholderMessage(0)}
                analyzing={isAnalyzing(0)}
              />
            )}

            {/* 레시피 추천 (단계 1) — 파이프라인 순서상 영양 검증보다 먼저 */}
            {revealedAt(1) ? (
              <div className="animate-reveal h-full [&>section]:h-full">
                <RecipesCard recipes={result!.recipes} />
              </div>
            ) : (
              <PlaceholderCard
                icon="👨‍🍳"
                title="레시피 추천"
                message={placeholderMessage(1)}
                analyzing={isAnalyzing(1)}
              />
            )}

            {/* 영양 검증 (Meal 단계 2 에 포함) */}
            {revealedAt(2) ? (
              <div className="animate-reveal h-full [&>section]:h-full">
                <NutritionCard nutrition={result!.nutrition} />
              </div>
            ) : (
              <PlaceholderCard
                icon="🥗"
                title="영양 검증"
                message={placeholderMessage(2)}
                analyzing={isAnalyzing(2)}
              />
            )}

            {/* 식단 플랜 (단계 2) */}
            {revealedAt(2) ? (
              <div className="animate-reveal h-full [&>section]:h-full">
                <MealPlanCard
                  mealPlan={result!.mealPlan}
                  mode={result!.mode}
                  nutrition={result!.nutrition}
                />
              </div>
            ) : (
              <PlaceholderCard
                icon="📅"
                title="식단 플랜"
                message={placeholderMessage(2)}
                analyzing={isAnalyzing(2)}
              />
            )}
          </div>

          {/* 부족 재료 & 쿠팡 실행 (Shopping 단계 3) */}
          {revealedAt(3) ? (
            <div className="animate-reveal">
              <CartExecutionCard shopping={result!.shopping} />
            </div>
          ) : (
            <PlaceholderCard
              icon="🛒"
              title="부족 재료 & 쿠팡 실행"
              message={placeholderMessage(3)}
              analyzing={isAnalyzing(3)}
            />
          )}
        </div>

        {/* 우: Agent Pipeline (항상 표시, 단계 상태와 함께 진행) */}
        <div className="hidden w-72 shrink-0 overflow-y-auto xl:block">
          <AgentPipelinePanel pipeline={buildPipeline()} />
        </div>
      </main>
    </div>
  );
}
