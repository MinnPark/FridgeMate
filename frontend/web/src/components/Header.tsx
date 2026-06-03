import { getApiMode } from "@/lib/api/client";

// 컴팩트 상단 헤더: 좌(서비스명) · 중(핵심 문구) · 우(API 상태 배지).
export function Header() {
  const mode = getApiMode();
  return (
    <header className="flex shrink-0 items-center gap-4 px-5 py-2.5">
      <div className="flex items-center gap-2">
        <span className="text-xl">🧊</span>
        <h1 className="text-base font-bold tracking-tight">FridgeMate AI</h1>
      </div>

      <p className="hidden flex-1 text-center text-xs text-white/55 md:block">
        추천이 아니라 검증과 실행까지 끝내는{" "}
        <span className="font-semibold text-lime-accent">End-to-End 자동화</span>
      </p>

      <span
        className={[
          "ml-auto flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium md:ml-0",
          mode === "mock"
            ? "bg-gold/15 text-gold"
            : "bg-lime-accent/15 text-lime-accent",
        ].join(" ")}
        title="NEXT_PUBLIC_USE_MOCK_API 로 전환"
      >
        <span className="h-1.5 w-1.5 rounded-full bg-current" />
        API: {mode}
      </span>
    </header>
  );
}
