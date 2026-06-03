"use client";

import { useCallback, useEffect, useState } from "react";

import { AgentPipelinePanel } from "@/components/AgentPipelinePanel";
import { CartExecutionCard } from "@/components/CartExecutionCard";
import { ConditionBar } from "@/components/ConditionBar";
import { Header } from "@/components/Header";
import { InputPanel } from "@/components/InputPanel";
import { MealPlanCard } from "@/components/MealPlanCard";
import { NutritionCard } from "@/components/NutritionCard";
import { PantryCard } from "@/components/PantryCard";
import { RecipesCard } from "@/components/RecipesCard";
import { runPipeline } from "@/lib/api/client";
import { DEFAULT_INGREDIENT_ENTRIES, DEMO_REQUEST } from "@/lib/api/mock";
import type {
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

// 한 페이지 End-to-End 대시보드: 상단 헤더 / 좌(메인) · 우(Agent Pipeline) 2열.
export default function HomePage() {
  const [ingredients, setIngredients] = useState<IngredientEntry[]>(
    DEFAULT_INGREDIENT_ENTRIES,
  );
  const [request, setRequest] = useState<FridgeMateRequest>(DEMO_REQUEST);
  const [result, setResult] = useState<RunResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = useCallback(async () => {
    if (ingredients.length === 0) {
      setError("재료를 1개 이상 입력해 주세요.");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const req: FridgeMateRequest = {
        ...request,
        ingredients: ingredients.map((i) => i.name).join(", "),
      };
      const { data, notice } = await runPipeline(req);
      if (!isValidRunResponse(data)) {
        setError("결과 형식이 올바르지 않아요. 잠시 후 다시 시도해 주세요.");
        return;
      }
      setResult(data);
      if (notice) setError("백엔드 연결에 실패했습니다. 현재는 예시 결과를 표시합니다.");
    } catch (e) {
      console.error(e);
      setError("분석에 실패했습니다. 잠시 후 다시 시도해 주세요.");
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ingredients, request]);

  // 진입 시 1회 자동 실행.
  useEffect(() => {
    void run();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function addIngredient(entry: IngredientEntry) {
    setIngredients((prev) =>
      prev.some((i) => i.name === entry.name) ? prev : [...prev, entry],
    );
  }
  function removeIngredient(name: string) {
    setIngredients((prev) => prev.filter((i) => i.name !== name));
  }

  return (
    <div className="mx-auto flex h-screen max-w-[1600px] flex-col overflow-hidden">
      <Header />

      <main className="flex flex-1 gap-4 overflow-hidden px-4 pb-4">
        {/* 좌: 메인 대시보드 */}
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
            loading={loading}
          />

          <ConditionBar value={request} onChange={setRequest} />

          {error && (
            <div className="rounded-xl border border-amber-400/30 bg-amber-400/10 px-4 py-2 text-sm text-amber-200">
              {error}
            </div>
          )}

          {result ? (
            <>
              <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                <PantryCard pantry={result.pantry} ingredients={ingredients} />
                <NutritionCard nutrition={result.nutrition} />
                <RecipesCard recipes={result.recipes} />
                <MealPlanCard
                  mealPlan={result.mealPlan}
                  mode={result.mode}
                  nutrition={result.nutrition}
                />
              </div>

              <CartExecutionCard shopping={result.shopping} />
            </>
          ) : (
            <div className="fm-card grid flex-1 place-items-center text-white/40">
              {loading
                ? "분석 중입니다…"
                : "재료를 입력하고 “분석 실행”을 눌러 주세요."}
            </div>
          )}
        </div>

        {/* 우: Agent Pipeline (데스크톱 고정 패널) */}
        {result && (
          <div className="hidden w-72 shrink-0 overflow-y-auto xl:block">
            <AgentPipelinePanel pipeline={result.pipeline} />
          </div>
        )}
      </main>
    </div>
  );
}
