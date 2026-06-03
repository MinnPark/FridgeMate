"use client";

import { useState } from "react";

import type {
  FridgeMateMode,
  MealPlan,
  NutritionVerification,
} from "@/lib/api/types";

import { Modal } from "./Modal";

const MODE_LABEL: Record<FridgeMateMode, string> = {
  today: "Today",
  weekend: "Weekend",
  meal_prep: "Meal Prep",
  goal: "Goal",
};

interface Props {
  mealPlan: MealPlan;
  mode: FridgeMateMode;
  nutrition: NutritionVerification;
}

export function MealPlanCard({ mealPlan, mode, nutrition }: Props) {
  const [open, setOpen] = useState(false);
  const firstDay = mealPlan.days[0];

  return (
    <section className="fm-card flex flex-col p-4">
      <h3 className="mb-2 flex items-center gap-1.5 text-sm font-bold">
        📅 식단 플랜
      </h3>

      <div className="flex-1 space-y-1.5">
        <span className="inline-block rounded-full bg-lime-accent/15 px-2 py-0.5 text-[11px] font-medium text-lime-accent">
          {MODE_LABEL[mode]}
        </span>
        <p className="text-xs text-white/60">
          하루 단백질 {nutrition.protein.current}
          {nutrition.protein.unit}
        </p>
        <p className="text-xs text-white/60">
          칼로리 {nutrition.calories.current}
          {nutrition.calories.unit}
        </p>
      </div>

      <button
        onClick={() => setOpen(true)}
        className="mt-2 flex items-center justify-between rounded-lg bg-white/5 px-3 py-2 text-xs text-white/65 transition hover:bg-white/10"
      >
        전체 식단 보기 <span>›</span>
      </button>

      <Modal
        open={open}
        onClose={() => setOpen(false)}
        title="식단 플랜"
        icon="📅"
        widthClass="max-w-2xl"
      >
        <div className="grid gap-3 sm:grid-cols-3">
          {mealPlan.days.map((day) => (
            <div
              key={day.label}
              className="rounded-xl border border-white/5 bg-white/[0.03] p-3"
            >
              <p className="mb-2 text-sm font-semibold text-white/80">
                {day.label}
              </p>
              <ul className="space-y-1.5">
                {day.entries.map((e, i) => (
                  <li key={i} className="text-xs">
                    <span className="text-white/40">{e.slot}</span>{" "}
                    <span
                      className={
                        e.usesPriorityItem
                          ? "font-medium text-lime-accent"
                          : "text-white/75"
                      }
                    >
                      {e.recipeTitle}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
        {mealPlan.note && (
          <p className="mt-3 flex items-center gap-1.5 text-xs text-white/55">
            <span className="h-2 w-2 rounded-full bg-lime-accent" />
            {mealPlan.note}
          </p>
        )}
      </Modal>
    </section>
  );
}
