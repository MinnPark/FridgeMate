"use client";

import { useState } from "react";

import type { Recipe } from "@/lib/api/types";

import { Modal } from "./Modal";
import { RecipeScore, ScoreReasons } from "./ScoreBadge";

interface Props {
  recipes: Recipe[];
}

export function RecipesCard({ recipes }: Props) {
  const [open, setOpen] = useState(false);
  const top = recipes[0];

  return (
    <section className="fm-card flex flex-col p-4">
      <h3 className="mb-2 flex items-center gap-1.5 text-sm font-bold">
        👨‍🍳 레시피 추천
      </h3>

      {top ? (
        <div className="flex-1">
          <p className="text-sm font-semibold">{top.title}</p>
          <div className="mt-1 flex flex-wrap items-center gap-1.5 text-[11px]">
            {top.cookMinutes !== undefined && (
              <span className="text-white/45">⏱️ {top.cookMinutes}분</span>
            )}
            {top.tags.slice(0, 2).map((t) => (
              <span
                key={t}
                className="rounded-full bg-white/5 px-1.5 py-0.5 text-white/70"
              >
                {t}
              </span>
            ))}
          </div>
          {recipes.length > 1 && (
            <p className="mt-1 text-[11px] text-white/40">
              외 {recipes.length - 1}개 후보
            </p>
          )}
        </div>
      ) : (
        <p className="flex-1 text-sm text-white/50">추천 레시피가 없어요.</p>
      )}

      <button
        onClick={() => setOpen(true)}
        className="mt-2 flex items-center justify-between rounded-lg bg-white/5 px-3 py-2 text-xs text-white/65 transition hover:bg-white/10"
      >
        레시피 펼치기 <span>›</span>
      </button>

      <Modal
        open={open}
        onClose={() => setOpen(false)}
        title="레시피 추천"
        icon="👨‍🍳"
        widthClass="max-w-3xl"
        headerRight={
          <span className="text-xs text-white/45">{recipes.length}개 후보</span>
        }
      >
        <div className="space-y-3">
          {recipes.map((r) => (
            <article
              key={r.id}
              className="rounded-xl border border-white/5 bg-white/[0.03] p-4"
            >
              <div className="flex items-start justify-between gap-2">
                <h4 className="font-semibold">{r.title}</h4>
                <span className="shrink-0 text-xs text-white/45">
                  {[
                    r.cookMinutes !== undefined ? `⏱️ ${r.cookMinutes}분` : null,
                    r.servings !== undefined ? `👤 ${r.servings}인분` : null,
                  ]
                    .filter(Boolean)
                    .join(" · ") || "조리시간 미제공"}
                </span>
              </div>
              <p className="mt-1 text-sm text-white/60">{r.description}</p>
              <div className="mt-2 flex flex-wrap gap-1.5">
                {r.tags.map((t) => (
                  <span
                    key={t}
                    className="rounded-full bg-white/5 px-2 py-0.5 text-[11px] text-white/70"
                  >
                    {t}
                  </span>
                ))}
              </div>
              {r.mainIngredients.length > 0 && (
                <p className="mt-2 text-xs text-white/50">
                  <span className="text-white/40">재료 </span>
                  {r.mainIngredients.join(", ")}
                </p>
              )}
              <RecipeScore score={r.score} />
              <ScoreReasons reasons={r.score?.reasons} />
              <div className="mt-2.5 flex flex-wrap items-center gap-1.5 border-t border-white/5 pt-2">
                <span className="rounded-md bg-white/10 px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-white/50">
                  source
                </span>
                {r.citations.map((c, i) => (
                  <span key={i} className="text-[11px] text-white/50">
                    {c.url ? (
                      <a
                        href={c.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="underline decoration-white/20 hover:text-white/80"
                      >
                        {c.label}
                      </a>
                    ) : (
                      c.label
                    )}
                  </span>
                ))}
              </div>
            </article>
          ))}
        </div>
      </Modal>
    </section>
  );
}
