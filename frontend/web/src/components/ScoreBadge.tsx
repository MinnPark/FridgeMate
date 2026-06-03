import type { ScoreInfo } from "@/lib/api/types";

// 점수 표시 전용 컴포넌트. 값은 mock/백엔드가 내려준 것만 표시한다(프론트 계산 X).

function pct(v?: number): string | null {
  if (v === undefined) return null;
  // 0~1 유사도는 %로, 0~100 점수는 그대로.
  return v <= 1 ? `${Math.round(v * 100)}` : `${Math.round(v)}`;
}

function Chip({ label, value }: { label: string; value?: number }) {
  const shown = pct(value);
  if (shown === null) return null;
  return (
    <span className="rounded-md bg-white/5 px-1.5 py-0.5 text-[11px] text-white/70">
      {label} <span className="font-semibold text-lime-accent">{shown}</span>
    </span>
  );
}

/** 레시피 점수(기본/제철/트렌드/최종) 표시. */
export function RecipeScore({ score }: { score?: ScoreInfo }) {
  if (!score) return null;
  return (
    <div className="mt-2 flex flex-wrap items-center gap-1.5">
      <Chip label="기본" value={score.baseScore} />
      <Chip label="제철+" value={score.seasonalBonus} />
      <Chip label="트렌드+" value={score.trendBonus} />
      <Chip label="최종" value={score.finalScore} />
    </div>
  );
}

/** 상품 점수(상품/배송/가격/신선/영양) 표시. */
export function ProductScore({ score }: { score?: ScoreInfo }) {
  if (!score) return null;
  return (
    <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
      <Chip label="상품" value={score.shoppingScore} />
      <Chip label="배송" value={score.deliveryScore} />
      <Chip label="가격" value={score.priceScore} />
      <Chip label="신선" value={score.freshnessScore} />
      <Chip label="영양" value={score.nutritionFitScore} />
    </div>
  );
}

/** 점수 산정 이유 문구. */
export function ScoreReasons({ reasons }: { reasons?: string[] }) {
  if (!reasons || reasons.length === 0) return null;
  return (
    <ul className="mt-1.5 flex flex-wrap gap-1">
      {reasons.map((r, i) => (
        <li
          key={i}
          className="rounded-full bg-lime-accent/10 px-2 py-0.5 text-[11px] text-lime-accent/90"
        >
          {r}
        </li>
      ))}
    </ul>
  );
}
