"use client";

import { useState } from "react";

import type { NutrientMetric, NutritionVerification } from "@/lib/api/types";

import { Modal } from "./Modal";

interface Props {
  nutrition: NutritionVerification;
}

export function NutritionCard({ nutrition }: Props) {
  const [open, setOpen] = useState(false);

  const badge = (
    <span
      className={[
        "rounded-full px-2 py-0.5 text-[11px] font-semibold",
        nutrition.passed
          ? "bg-lime-accent/15 text-lime-accent"
          : "bg-amber-400/15 text-amber-300",
      ].join(" ")}
    >
      {nutrition.passed ? "PASS" : "보완 필요"}
    </span>
  );

  return (
    <section className="fm-card flex flex-col p-4">
      <div className="mb-2 flex items-center gap-2">
        <h3 className="flex items-center gap-1.5 text-sm font-bold">🥗 영양 검증</h3>
        <div className="ml-auto">{badge}</div>
      </div>

      <div className="flex-1 space-y-2">
        <KeyBar label="단백질" m={nutrition.protein} />
        <KeyBar label="칼로리" m={nutrition.calories} />
      </div>

      <button
        onClick={() => setOpen(true)}
        className="mt-2 flex items-center justify-between rounded-lg bg-white/5 px-3 py-2 text-xs text-white/65 transition hover:bg-white/10"
      >
        자세히 보기 <span>›</span>
      </button>

      <Modal
        open={open}
        onClose={() => setOpen(false)}
        title="영양 검증"
        icon="🥗"
        headerRight={badge}
      >
        <div className="space-y-2.5">
          <Bar icon="💪" label="단백질" m={nutrition.protein} />
          <Bar icon="🔥" label="칼로리" m={nutrition.calories} />
          {nutrition.carbs && <Bar icon="🍚" label="탄수화물" m={nutrition.carbs} />}
          {nutrition.fat && <Bar icon="🥑" label="지방" m={nutrition.fat} />}
        </div>
        <p className="mt-3 rounded-xl bg-white/5 px-3 py-2 text-sm text-white/75">
          {nutrition.message}
        </p>
        {nutrition.notProvided && nutrition.notProvided.length > 0 && (
          <p className="mt-2 rounded-lg bg-white/5 px-3 py-2 text-xs text-white/50">
            미제공(백엔드 연동 대기): {nutrition.notProvided.join(", ")}
          </p>
        )}
        {nutrition.warnings && nutrition.warnings.length > 0 && (
          <ul className="mt-2 space-y-1">
            {nutrition.warnings.map((w, i) => (
              <li key={i} className="text-xs text-amber-300/90">
                ⚠️ {w}
              </li>
            ))}
          </ul>
        )}
      </Modal>
    </section>
  );
}

function pct(m: NutrientMetric) {
  return m.target > 0 ? Math.min(100, Math.round((m.current / m.target) * 100)) : 0;
}

function KeyBar({ label, m }: { label: string; m: NutrientMetric }) {
  return (
    <div>
      <div className="mb-0.5 flex items-center justify-between text-xs">
        <span className="text-white/55">{label}</span>
        <span className="text-white/70">
          <b className="text-white/90">{m.current}</b> / {m.target}
          {m.unit}
        </span>
      </div>
      <div className="h-1.5 overflow-hidden rounded-full bg-white/10">
        <div
          className="h-full rounded-full bg-lime-accent/80"
          style={{ width: `${pct(m)}%` }}
        />
      </div>
    </div>
  );
}

function Bar({
  icon,
  label,
  m,
}: {
  icon: string;
  label: string;
  m: NutrientMetric;
}) {
  return (
    <div>
      <div className="mb-1 flex items-center justify-between text-xs">
        <span className="flex items-center gap-1 text-white/70">
          {icon} {label}
        </span>
        <span className="text-white/55">
          {m.current} / {m.target} {m.unit}
        </span>
      </div>
      <div className="h-1.5 overflow-hidden rounded-full bg-white/10">
        <div
          className="h-full rounded-full bg-lime-accent/80"
          style={{ width: `${pct(m)}%` }}
        />
      </div>
    </div>
  );
}
