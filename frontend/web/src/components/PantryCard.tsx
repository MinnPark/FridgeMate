"use client";

import { useState } from "react";

import type {
  FreshnessLevel,
  IngredientEntry,
  PantryAnalysis,
} from "@/lib/api/types";

import { Modal } from "./Modal";

const FRESHNESS: Record<FreshnessLevel, { label: string; cls: string }> = {
  fresh: { label: "신선", cls: "bg-lime-accent/15 text-lime-accent" },
  soon: { label: "임박", cls: "bg-amber-400/15 text-amber-300" },
  urgent: { label: "임박", cls: "bg-red-500/20 text-red-300" },
};

interface Props {
  pantry: PantryAnalysis;
  ingredients: IngredientEntry[]; // 사용자가 입력한 재료(용량/유통기한)
}

export function PantryCard({ pantry, ingredients }: Props) {
  const [open, setOpen] = useState(false);

  return (
    <section className="fm-card flex flex-col p-4">
      <h3 className="mb-2 flex items-center gap-1.5 text-sm font-bold">
        🧺 Pantry 분석
      </h3>
      <div className="flex-1 space-y-1 text-sm">
        <p className="text-white/70">
          주요 재료 <span className="font-semibold">{pantry.items.length}종</span>
        </p>
        {pantry.priorityUse.length > 0 && (
          <p className="text-xs">
            <span className="text-white/45">우선 사용 </span>
            <span className="font-medium text-amber-300">
              {pantry.priorityUse.join(", ")}
            </span>
          </p>
        )}
      </div>

      <button
        onClick={() => setOpen(true)}
        className="mt-2 flex items-center justify-between rounded-lg bg-white/5 px-3 py-2 text-xs text-white/65 transition hover:bg-white/10"
      >
        자세히 보기 <span>›</span>
      </button>

      <Modal open={open} onClose={() => setOpen(false)} title="Pantry 분석" icon="🧺">
        <p className="mb-3 rounded-lg bg-white/5 px-3 py-2 text-sm text-white/70">
          {pantry.summary}
        </p>

        <p className="mb-1.5 text-xs font-semibold text-white/55">입력한 재료</p>
        <div className="overflow-hidden rounded-xl border border-white/5">
          <table className="w-full text-left text-xs">
            <thead className="bg-white/[0.04] text-white/45">
              <tr>
                <th className="px-3 py-2">재료</th>
                <th className="px-3 py-2">용량</th>
                <th className="px-3 py-2">유통기한</th>
                <th className="px-3 py-2">보관</th>
              </tr>
            </thead>
            <tbody>
              {ingredients.map((it) => (
                <tr key={it.name} className="border-t border-white/5">
                  <td className="px-3 py-2 font-medium">{it.name}</td>
                  <td className="px-3 py-2 text-white/60">{it.amount ?? "-"}</td>
                  <td className="px-3 py-2 text-white/60">
                    {it.expirationDate ?? "-"}
                  </td>
                  <td className="px-3 py-2 text-white/50">
                    {it.storageType ?? "-"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <p className="mb-1.5 mt-4 text-xs font-semibold text-white/55">
          분석 결과 (임박 재료 우선 사용)
        </p>
        <ul className="space-y-1.5">
          {pantry.items.map((item) => {
            const f = FRESHNESS[item.freshness];
            return (
              <li key={item.name} className="flex items-center gap-2 text-sm">
                <span className="font-medium">{item.name}</span>
                <span className="text-xs text-white/40">{item.category}</span>
                <span
                  className={`ml-auto rounded-md px-1.5 py-0.5 text-[11px] font-semibold ${f.cls}`}
                >
                  {item.expiryLabel ? `${f.label} ${item.expiryLabel}` : f.label}
                </span>
              </li>
            );
          })}
        </ul>
        <div className="mt-3 rounded-xl bg-amber-400/10 px-3 py-2 text-sm text-amber-200/90">
          임박 재료 우선 사용 예정: {pantry.priorityUse.join(", ")}
        </div>
      </Modal>
    </section>
  );
}
