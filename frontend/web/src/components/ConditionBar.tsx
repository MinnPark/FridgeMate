"use client";

import type {
  DeliveryPreference,
  FridgeMateRequest,
} from "@/lib/api/types";

interface Props {
  value: FridgeMateRequest;
  onChange: (next: FridgeMateRequest) => void;
}

function num(raw: string): number | undefined {
  if (raw === "") return undefined;
  const n = Number(raw);
  return Number.isNaN(n) ? undefined : n;
}

// 목표/조건 입력 줄. 목표·배송 선호는 select, 나머지 수치는 직접 입력.
export function ConditionBar({ value, onChange }: Props) {
  function patch(p: Partial<FridgeMateRequest>) {
    onChange({ ...value, ...p });
  }

  return (
    <section className="fm-card grid grid-cols-2 gap-x-4 gap-y-2 px-5 py-3 md:grid-cols-4">
      <Field label="목표">
        <select
          value={value.goal ?? "고단백 저탄수"}
          onChange={(e) => patch({ goal: e.target.value })}
          className={cls}
        >
          {["고단백 저탄수", "균형", "저칼로리", "고단백"].map((o) => (
            <option key={o}>{o}</option>
          ))}
        </select>
      </Field>

      <Field label="단백질(g)">
        <input
          type="number"
          min={0}
          value={value.proteinTargetGram ?? ""}
          onChange={(e) => patch({ proteinTargetGram: num(e.target.value) })}
          placeholder="120"
          className={cls}
        />
      </Field>

      <Field label="칼로리(kcal)">
        <input
          type="number"
          min={0}
          value={value.calorieTargetKcal ?? ""}
          onChange={(e) => patch({ calorieTargetKcal: num(e.target.value) })}
          placeholder="1700"
          className={cls}
        />
      </Field>

      <Field label="예산(원)">
        <input
          type="number"
          min={0}
          value={value.budgetKrw ?? ""}
          onChange={(e) => patch({ budgetKrw: num(e.target.value) })}
          placeholder="100000"
          className={cls}
        />
      </Field>

      <Field label="인원(명)">
        <input
          type="number"
          min={1}
          value={value.peopleCount ?? ""}
          onChange={(e) => patch({ peopleCount: num(e.target.value) })}
          placeholder="2"
          className={cls}
        />
      </Field>

      <Field label="조리시간(분)">
        <input
          type="number"
          min={0}
          value={value.maxCookingMinutes ?? ""}
          onChange={(e) => patch({ maxCookingMinutes: num(e.target.value) })}
          placeholder="20"
          className={cls}
        />
      </Field>

      <Field label="제외 재료">
        <input
          value={value.excludedIngredients ?? ""}
          onChange={(e) =>
            patch({ excludedIngredients: e.target.value || undefined })
          }
          placeholder="예: 해산물"
          className={cls}
        />
      </Field>

      <Field label="배송 선호">
        <select
          value={value.deliveryPreference ?? "speed"}
          onChange={(e) =>
            patch({ deliveryPreference: e.target.value as DeliveryPreference })
          }
          className={cls}
        >
          <option value="speed">빠른 배송</option>
          <option value="price">가격</option>
        </select>
      </Field>
    </section>
  );
}

const cls =
  "min-w-0 flex-1 rounded-lg border border-white/10 bg-black/20 px-2.5 py-1.5 text-sm outline-none focus:border-lime-accent/60 [color-scheme:dark]";

function Field({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <label className="flex items-center gap-2">
      <span className="w-24 shrink-0 text-xs text-white/45">{label}</span>
      {children}
    </label>
  );
}
