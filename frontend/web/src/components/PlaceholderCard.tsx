// 분석 전/대기/진행 중 상태에서 결과 카드 자리를 채우는 placeholder (역할 D)
//
// 기존 결과 카드와 동일한 fm-card 외형으로 같은 그리드 셀을 차지해, 분석 전·중·후
// 레이아웃이 흔들리지 않게 한다. 메시지("분석 전입니다" / "분석 중입니다…" / "대기 중")는
// page.tsx 가 단계 상태에 맞춰 계산해 넘긴다.

interface Props {
  icon: string;
  title: string;
  message: string;
  analyzing?: boolean; // 진행 중이면 살짝 강조(테두리/펄스)
}

export function PlaceholderCard({ icon, title, message, analyzing = false }: Props) {
  return (
    <section
      className={[
        "fm-card flex flex-col p-4",
        analyzing ? "border border-lime-accent/40" : "",
      ].join(" ")}
    >
      <h3 className="mb-2 flex items-center gap-1.5 text-sm font-bold">
        {icon} {title}
      </h3>
      <div className="grid flex-1 place-items-center py-6 text-sm text-white/40">
        <span className={analyzing ? "animate-pulse text-lime-accent/80" : ""}>
          {message}
        </span>
      </div>
    </section>
  );
}
