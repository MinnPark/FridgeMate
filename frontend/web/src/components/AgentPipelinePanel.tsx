"use client";

import { useState } from "react";

import type { AgentPipelineItem, AgentStatus } from "@/lib/api/types";

const ICON: Record<string, string> = {
  pantry: "🧺",
  recipe: "👨‍🍳",
  meal: "📅",
  shopping: "🛒",
  executor: "⚡",
};

function dotCls(status: AgentStatus): string {
  switch (status) {
    case "completed":
      return "bg-lime-accent";
    case "running":
      return "bg-lime-accent animate-pulseGlow";
    case "failed":
      return "bg-red-400";
    default:
      return "bg-white/25";
  }
}

function badge(status: AgentStatus): string {
  switch (status) {
    case "completed":
      return "✓";
    case "running":
      return "…";
    case "failed":
      return "!";
    default:
      return "·";
  }
}

interface Props {
  pipeline: AgentPipelineItem[];
}

// 오른쪽 Agent Pipeline 패널. 기본은 이름+상태+한 줄 메시지만, 로그는 접어둔다.
export function AgentPipelinePanel({ pipeline }: Props) {
  const ordered = [...pipeline].sort((a, b) => a.order - b.order);
  const completed = ordered.filter((s) => s.status === "completed").length;
  const running = ordered.some((s) => s.status === "running") ? 0.5 : 0;
  const progress = Math.round(((completed + running) / ordered.length) * 100);

  return (
    <aside className="fm-card flex w-full shrink-0 flex-col gap-4 p-4 xl:w-72">
      <div className="flex items-center justify-between">
        <h3 className="text-base font-bold">Agent Pipeline</h3>
        <span className="flex items-center gap-1 rounded-full bg-lime-accent/15 px-2 py-0.5 text-xs text-lime-accent">
          ● 실시간
        </span>
      </div>

      <ol className="flex flex-col gap-2.5">
        {ordered.map((step) => (
          <AgentRow key={step.id} step={step} />
        ))}
      </ol>

      <div>
        <div className="mb-1 flex items-center justify-between text-xs text-white/55">
          <span>진행률</span>
          <span className="font-semibold text-lime-accent">{progress}%</span>
        </div>
        <div className="h-2 overflow-hidden rounded-full bg-white/10">
          <div
            className="h-full rounded-full bg-lime-accent transition-all"
            style={{ width: `${progress}%` }}
          />
        </div>
      </div>
    </aside>
  );
}

function AgentRow({ step }: { step: AgentPipelineItem }) {
  const [open, setOpen] = useState(false);
  const active = step.status === "running";
  const hasLogs = Boolean(step.logs && step.logs.length > 0);

  return (
    <li
      className={[
        "rounded-xl border p-3 transition",
        active ? "border-lime-accent/60 bg-lime-accent/5" : "border-white/5 bg-white/[0.03]",
      ].join(" ")}
    >
      <div className="flex items-start gap-3">
        <span className="grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-white/5 text-base">
          {ICON[step.id] ?? "•"}
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex items-center justify-between gap-2">
            <span className="truncate text-sm font-semibold">
              {step.order}. {step.name}
            </span>
            <span
              className={[
                "grid h-4 w-4 place-items-center rounded-full text-[10px] text-ink-900",
                dotCls(step.status),
              ].join(" ")}
            >
              {badge(step.status)}
            </span>
          </div>
          <p className="mt-0.5 truncate text-xs text-white/55">{step.message}</p>

          {hasLogs && (
            <>
              <button
                onClick={() => setOpen((v) => !v)}
                aria-expanded={open}
                className="mt-1.5 text-[11px] text-white/40 hover:text-white/70"
              >
                {open ? "로그 접기 ▾" : `로그 보기 (${step.logs!.length}) ▸`}
              </button>
              {open && (
                <ul className="mt-1 space-y-0.5 font-mono text-[10.5px] text-white/45">
                  {step.logs!.map((log, i) => (
                    <li key={i} className="truncate">
                      › {log}
                    </li>
                  ))}
                </ul>
              )}
            </>
          )}
        </div>
      </div>
    </li>
  );
}
