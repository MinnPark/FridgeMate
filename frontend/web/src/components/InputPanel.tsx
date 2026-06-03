"use client";

import { useState } from "react";

import type {
  FridgeMateMode,
  IngredientEntry,
} from "@/lib/api/types";

import { IngredientDetailModal } from "./IngredientDetailModal";

const MODES: { key: FridgeMateMode; icon: string; label: string }[] = [
  { key: "today", icon: "☀️", label: "Today" },
  { key: "weekend", icon: "🗓️", label: "Weekend" },
  { key: "meal_prep", icon: "🍱", label: "Meal Prep" },
  { key: "goal", icon: "🎯", label: "Goal" },
];

const EMOJI: Record<string, string> = {
  닭가슴살: "🍗",
  계란: "🥚",
  브로콜리: "🥦",
  두부: "🧈",
  그릭요거트: "🥛",
};

interface Props {
  ingredients: IngredientEntry[];
  onAddIngredient: (entry: IngredientEntry) => void;
  onRemoveIngredient: (name: string) => void;
  mode: FridgeMateMode;
  onModeChange: (m: FridgeMateMode) => void;
  onRun: () => void;
  loading: boolean;
}

// 컴팩트 입력 카드: 재료 chip(한 줄) + 시나리오 모드 + 분석 실행 버튼.
// 재료명 입력 후 Enter → 상세 입력 팝업(용량/유통기한) → 팬트리 반영.
export function InputPanel({
  ingredients,
  onAddIngredient,
  onRemoveIngredient,
  mode,
  onModeChange,
  onRun,
  loading,
}: Props) {
  const [draft, setDraft] = useState("");
  const [pendingName, setPendingName] = useState<string | null>(null);

  function onEnter() {
    const v = draft.trim();
    if (!v) return;
    if (ingredients.some((i) => i.name === v)) {
      setDraft("");
      return;
    }
    setPendingName(v); // 바로 추가하지 않고 상세 입력 팝업을 띄운다.
  }

  return (
    <section className="fm-card px-5 py-4">
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="mr-1 flex items-center gap-1.5 text-sm font-bold text-white/90">
          🧊 냉장고 재료 입력
        </h2>

        {/* 재료 칩 (한 줄 위주, wrap) */}
        {ingredients.map((it) => (
          <span
            key={it.name}
            className="flex items-center gap-1.5 rounded-full border border-white/10 bg-white/5 px-2.5 py-1 text-sm"
            title={[it.amount, it.expirationDate].filter(Boolean).join(" · ")}
          >
            <span>{EMOJI[it.name] ?? "🍽️"}</span>
            {it.name}
            {it.amount && (
              <span className="text-[11px] text-white/40">{it.amount}</span>
            )}
            <button
              onClick={() => onRemoveIngredient(it.name)}
              className="ml-0.5 text-white/40 hover:text-white/80"
              aria-label={`${it.name} 삭제`}
            >
              ✕
            </button>
          </span>
        ))}

        <input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && onEnter()}
          placeholder="+ 재료 추가 후 Enter"
          className="min-w-[150px] flex-1 rounded-full border border-dashed border-white/20 bg-transparent px-3 py-1 text-sm outline-none placeholder:text-white/40 focus:border-lime-accent/60"
        />

        <button
          onClick={onRun}
          disabled={loading}
          className="flex items-center gap-1.5 rounded-full bg-gold px-5 py-1.5 text-sm font-bold text-ink-900 transition hover:brightness-105 disabled:opacity-60"
        >
          {loading ? "분석 중…" : "✨ 분석 실행"}
        </button>
      </div>

      {/* 시나리오 모드 (같은 카드, 간결) */}
      <div className="mt-3 flex flex-wrap items-center gap-1.5">
        <span className="mr-1 text-xs text-white/45">시나리오</span>
        {MODES.map((m) => {
          const active = m.key === mode;
          return (
            <button
              key={m.key}
              onClick={() => onModeChange(m.key)}
              className={[
                "flex items-center gap-1 rounded-full px-3 py-1 text-xs transition",
                active
                  ? "bg-lime-accent font-semibold text-ink-900"
                  : "bg-white/5 text-white/65 hover:bg-white/10",
              ].join(" ")}
            >
              <span>{m.icon}</span>
              {m.label}
            </button>
          );
        })}
      </div>

      <IngredientDetailModal
        open={pendingName !== null}
        name={pendingName ?? ""}
        onCancel={() => {
          setPendingName(null);
          setDraft("");
        }}
        onAdd={(entry) => {
          onAddIngredient(entry);
          setPendingName(null);
          setDraft("");
        }}
      />
    </section>
  );
}
