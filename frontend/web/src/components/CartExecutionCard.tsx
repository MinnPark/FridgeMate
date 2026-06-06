"use client";

import { useEffect, useState } from "react";

import {
  formatKRW,
  openCoupangCartPage,
  openCoupangSearch,
} from "@/lib/api/coupang";
import {
  executeViaExtension,
  onExtensionReady,
  pingExtension,
  type ExecProgress,
} from "@/lib/api/extensionBridge";
import type {
  CartExecuteItem,
  CartExecuteResponse,
  ShoppingList,
} from "@/lib/api/types";
import { MOCK_CART_LINKS } from "@/lib/api/coupangMockLinks";

import { Modal } from "./Modal";

const IS_DEV = process.env.NODE_ENV !== "production";

type StepState = "done" | "running" | "pending";
type Phase = "idle" | "running" | "result";

interface Props {
  shopping: ShoppingList;
  // 실제 담기 실행 상태를 상위(Agent Pipeline의 Executor 단계)로 알린다.
  onStatusChange?: (status: "running" | "completed" | "failed") => void;
}

// 부족 재료 장보기 + 쿠팡 실행부 통합 카드.
// 좌: 부족 재료 요약 / 우: 분석 → 검색 URL 생성(자동) → 장바구니 담기(수동) 진행 상태.
// 자동 담기는 Chrome 확장으로 실행한다(결제 없음).
export function CartExecutionCard({ shopping, onStatusChange }: Props) {
  const [phase, setPhase] = useState<Phase>("idle");
  const [exec, setExec] = useState<CartExecuteResponse | null>(null);
  const [execError, setExecError] = useState<string | null>(null);
  const [progress, setProgress] = useState<{
    done: number;
    total: number;
    current?: string;
  } | null>(null);
  const [extReady, setExtReady] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [resultOpen, setResultOpen] = useState(false);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    const off = onExtensionReady(() => setExtReady(true));
    pingExtension();
    const t = setInterval(pingExtension, 2000);
    return () => {
      off();
      clearInterval(t);
    };
  }, []);

  const hasItems = shopping.items.length > 0;
  const searchUrl = shopping.coupangSearchUrl;
  const targetCount = shopping.items.filter((i) => i.productUrl).length;

  function buildExecItems(): CartExecuteItem[] {
    return shopping.items.map((i) => ({
      ingredient: i.name,
      productUrl: i.productUrl,
      searchUrl: i.productUrl ? undefined : searchUrl,
      quantity: 1,
    }));
  }

  const step3State: StepState =
    phase === "running" ? "running" : phase === "result" ? "done" : "pending";

  async function runItems(items: CartExecuteItem[]) {
    if (!extReady) {
      setExec(null);
      setExecError(
        "FridgeMate Cart Helper 확장 프로그램이 감지되지 않았어요. chrome://extensions 에서 frontend/extension 을 로드하고 쿠팡에 로그인한 뒤 다시 시도해 주세요.",
      );
      setPhase("result");
      onStatusChange?.("failed");
      return;
    }
    setPhase("running");
    setExec(null);
    setExecError(null);
    setProgress({ done: 0, total: items.length });
    onStatusChange?.("running");
    try {
      const res = await executeViaExtension(items, (p: ExecProgress) => {
        // 병렬 처리이므로 완료 수(done)는 item-done 기준으로만 증가시키고,
        // 진행 중 표시 이름은 item-start 에서 갱신한다(막대가 뒤로 가지 않도록).
        setProgress((prev) => {
          const base = prev ?? { done: 0, total: p.total };
          if (p.phase === "item-start") {
            return { ...base, total: p.total, current: p.itemName };
          }
          return { ...base, total: p.total, done: p.done ?? base.done };
        });
      });
      setExec(res);
      // 하나라도 담겼으면 Executor 단계 완료로 본다(부분 실패 포함).
      const anySuccess = res.results.some((r) => r.status === "success");
      onStatusChange?.(anySuccess ? "completed" : "failed");
    } catch (e) {
      setExecError(
        e instanceof Error ? e.message : "실제 장바구니 담기에 실패했습니다.",
      );
      onStatusChange?.("failed");
    } finally {
      setPhase("result");
      setProgress(null);
    }
  }

  async function runExecute() {
    setConfirmOpen(false);
    await runItems(buildExecItems());
  }

  async function copyUrl() {
    try {
      await navigator.clipboard.writeText(searchUrl);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard 불가 환경 무시 */
    }
  }

  const counts = exec
    ? {
        success: exec.results.filter((r) => r.status === "success").length,
        failed: exec.results.filter((r) => r.status === "failed").length,
        skipped: exec.results.filter((r) => r.status === "skipped").length,
      }
    : null;

  return (
    <section className="fm-card p-5">
      <div className="mb-3 flex items-center gap-2">
        <h3 className="flex items-center gap-1.5 text-base font-bold">
          🛒 부족 재료 &amp; 쿠팡 실행
        </h3>
        <span
          className={[
            "ml-auto rounded-full px-2 py-0.5 text-[11px]",
            extReady
              ? "bg-lime-accent/15 text-lime-accent"
              : "bg-white/10 text-white/55",
          ].join(" ")}
        >
          {extReady ? "확장 연결됨" : "확장 미연결"}
        </span>
      </div>

      <div className="grid gap-5 lg:grid-cols-2">
        {/* 좌: 부족 재료 요약 */}
        <div>
          <p className="mb-2 text-xs font-semibold text-white/55">
            부족 재료 {shopping.items.length}개
          </p>
          {hasItems ? (
            <ul className="space-y-1.5">
              {shopping.items.map((item) => (
                <li
                  key={item.name}
                  className="flex items-center gap-2 text-sm"
                >
                  <span className="font-medium">{item.name}</span>
                  <span className="text-xs text-white/40">{item.quantity}</span>
                  {item.isAlternative && (
                    <span className="rounded bg-amber-400/15 px-1 text-[10px] text-amber-300">
                      대체재
                    </span>
                  )}
                  <span className="ml-auto text-white/70">
                    {formatKRW(item.priceKrw)}
                  </span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-white/50">부족한 재료가 없어요.</p>
          )}
          <div className="mt-3 flex items-center justify-between border-t border-white/5 pt-2 text-sm">
            <span className="text-white/55">예상 총액</span>
            <span className="text-lg font-bold">
              {formatKRW(shopping.estimatedCostKrw)}
              {shopping.budgetKrw !== undefined && (
                <span
                  className={[
                    "ml-2 text-xs font-normal",
                    shopping.withinBudget ? "text-lime-accent" : "text-red-300",
                  ].join(" ")}
                >
                  예산 {shopping.withinBudget ? "이내" : "초과"}
                </span>
              )}
            </span>
          </div>
        </div>

        {/* 우: 실행 진행 상태 */}
        <div className="lg:border-l lg:border-white/5 lg:pl-5">
          <p className="mb-2 text-xs font-semibold text-white/55">실행 진행 상태</p>
          <ol className="space-y-2">
            <StepRow n={1} state="done" label="부족 재료 분석 완료" note="자동" />
            <StepRow
              n={2}
              state={searchUrl ? "done" : "pending"}
              label="쿠팡 검색 URL 생성 완료"
              note="자동"
            />
            <StepRow
              n={3}
              state={step3State}
              label="장바구니 담기"
              note={
                phase === "running"
                  ? `진행 중 ${progress?.done ?? 0}/${progress?.total ?? 0}`
                  : phase === "result"
                    ? counts
                      ? `완료 ${counts.success} · 실패 ${counts.failed} · 건너뜀 ${counts.skipped}`
                      : "완료"
                    : "사용자 클릭 필요"
              }
            />
          </ol>

          {/* 진행률 바 */}
          {phase === "running" && (
            <div className="mt-2">
              <div className="h-1.5 overflow-hidden rounded-full bg-white/10">
                <div
                  className="h-full rounded-full bg-lime-accent transition-all"
                  style={{
                    width: `${
                      progress && progress.total > 0
                        ? Math.round((progress.done / progress.total) * 100)
                        : 0
                    }%`,
                  }}
                />
              </div>
              <p className="mt-1 text-[11px] text-white/50">
                {progress?.current ? `담는 중: ${progress.current}` : "처리 중…"}
              </p>
            </div>
          )}

          {/* 보조 액션 */}
          <div className="mt-3 grid grid-cols-3 gap-1.5">
            <SmallBtn onClick={() => openCoupangSearch(searchUrl)} disabled={!searchUrl}>
              🔍 검색 결과
            </SmallBtn>
            <SmallBtn onClick={copyUrl} disabled={!searchUrl}>
              {copied ? "복사됨" : "🔗 URL 복사"}
            </SmallBtn>
            <SmallBtn onClick={() => openCoupangCartPage()}>↗ 열기</SmallBtn>
          </div>

          {/* 메인 실행 버튼 */}
          <button
            onClick={() => (phase === "running" ? undefined : setConfirmOpen(true))}
            disabled={phase === "running" || !hasItems}
            className="mt-2 w-full rounded-xl bg-gold py-2.5 text-sm font-bold text-ink-900 transition hover:brightness-105 disabled:opacity-60"
          >
            {phase === "running"
              ? "담는 중…"
              : phase === "result"
                ? "🤖 다시 담기 (Chrome 확장)"
                : "🤖 장바구니 담기 실행 (Chrome 확장)"}
          </button>

          {phase === "result" && (exec || execError) && (
            <button
              onClick={() => setResultOpen(true)}
              className="mt-1.5 w-full text-center text-[11px] text-white/50 underline decoration-white/20 hover:text-white/80"
            >
              결과 상세 보기
            </button>
          )}

          {/* dev 전용: 백엔드 URL 연동 전, mock 링크로 확장의 담기 경로(direct/adjust)를 검증 */}
          {IS_DEV && (
            <button
              onClick={() => (phase === "running" ? undefined : runItems(MOCK_CART_LINKS))}
              disabled={phase === "running"}
              className="mt-1.5 w-full rounded-lg border border-dashed border-white/20 bg-white/[0.03] py-1.5 text-[11px] text-white/55 transition hover:bg-white/10 disabled:opacity-40"
            >
              🧪 Mock 링크로 담기 테스트 ({MOCK_CART_LINKS.length}개 · dev)
            </button>
          )}
        </div>
      </div>

      {/* 안내 문구 */}
      <p className="mt-3 text-[11px] text-white/40">
        검색 URL 생성은 자동으로 완료됩니다. 장바구니 담기는 사용자 클릭이 필요하며,
        Chrome 확장 프로그램으로 실행됩니다. 쿠팡 로그인은 사용자 브라우저에서 직접
        진행하며, 결제는 자동으로 진행되지 않습니다.
      </p>
      {!extReady && (
        <p className="mt-1.5 rounded-lg bg-white/5 px-3 py-2 text-[11px] text-white/55">
          확장 프로그램 설치 필요: <code>chrome://extensions</code> → 개발자 모드 →
          “압축해제된 확장” → <code>frontend/extension</code> 로드 후 새로고침.
        </p>
      )}

      {/* 확인 모달 */}
      <Modal
        open={confirmOpen}
        onClose={() => setConfirmOpen(false)}
        title="장바구니 담기 실행 전 확인"
        icon="🛒"
      >
        <ul className="space-y-1 text-sm text-white/80">
          <li>
            담을 품목: <b>{shopping.items.length}개</b> (상품 URL 있는{" "}
            <b>{targetCount}개</b> 담기 시도)
          </li>
          <li className="text-white/60">
            {shopping.items.map((i) => i.name).join(", ")}
          </li>
          <li>
            예상 총액: <b>{formatKRW(shopping.estimatedCostKrw)}</b>
          </li>
        </ul>
        <ul className="mt-2 space-y-0.5 text-xs text-white/55">
          <li>• Chrome 확장 프로그램으로 쿠팡 장바구니 담기를 실행합니다.</li>
          <li>• 쿠팡 로그인은 사용자 브라우저에서 직접 진행해야 합니다.</li>
          <li>• 결제는 자동으로 진행되지 않습니다. 계정 정보는 저장하지 않습니다.</li>
        </ul>
        <div className="mt-4 flex gap-2">
          <button
            onClick={runExecute}
            className="flex-1 rounded-xl bg-gold py-2.5 text-sm font-bold text-ink-900 transition hover:brightness-105"
          >
            확인하고 실행
          </button>
          <button
            onClick={() => setConfirmOpen(false)}
            className="rounded-xl border border-white/10 bg-white/5 px-4 py-2.5 text-sm text-white/70 transition hover:bg-white/10"
          >
            취소
          </button>
        </div>
      </Modal>

      {/* 결과 모달 */}
      <Modal
        open={resultOpen}
        onClose={() => setResultOpen(false)}
        title="장바구니 담기 결과"
        icon="🛒"
      >
        {execError ? (
          <div className="rounded-xl border border-red-400/30 bg-red-500/10 px-4 py-3 text-sm text-red-200">
            <p className="font-semibold">실제 자동 담기에 실패했습니다.</p>
            <p className="mt-1 whitespace-pre-line text-xs text-red-200/80">
              {execError}
            </p>
          </div>
        ) : exec ? (
          <>
            <p className="mb-2 text-sm text-white/70">{exec.message}</p>
            <ul className="space-y-1.5 text-xs">
              {exec.results.map((r, i) => (
                <li key={i} className="flex items-center gap-2">
                  <span
                    className={[
                      "rounded px-1.5 py-0.5 text-[10px] font-semibold",
                      r.status === "success"
                        ? "bg-lime-accent/15 text-lime-accent"
                        : r.status === "skipped"
                          ? "bg-amber-400/15 text-amber-300"
                          : "bg-red-500/20 text-red-300",
                    ].join(" ")}
                  >
                    {r.status}
                  </span>
                  <span className="font-medium">{r.itemName}</span>
                  <span className="text-white/50">— {r.message}</span>
                </li>
              ))}
            </ul>
            <p className="mt-3 text-[11px] text-white/45">
              결제는 사용자가 직접 확인 후 진행해야 합니다.
            </p>
          </>
        ) : null}
      </Modal>
    </section>
  );
}

function StepRow({
  n,
  state,
  label,
  note,
}: {
  n: number;
  state: StepState;
  label: string;
  note?: string;
}) {
  const map: Record<StepState, { ch: string; cls: string }> = {
    done: { ch: "✓", cls: "bg-lime-accent text-ink-900" },
    running: { ch: "…", cls: "bg-lime-accent text-ink-900 animate-pulseGlow" },
    pending: { ch: String(n), cls: "bg-white/15 text-white/70" },
  };
  const m = map[state];
  return (
    <li
      className={[
        "flex items-center gap-2.5 rounded-lg border px-3 py-2",
        state === "running"
          ? "border-lime-accent/50 bg-lime-accent/5"
          : "border-white/5 bg-white/[0.03]",
      ].join(" ")}
    >
      <span
        className={`grid h-5 w-5 shrink-0 place-items-center rounded-full text-[11px] font-bold ${m.cls}`}
      >
        {m.ch}
      </span>
      <span className="text-sm text-white/80">{label}</span>
      {note && <span className="ml-auto text-[11px] text-white/45">{note}</span>}
    </li>
  );
}

function SmallBtn({
  onClick,
  disabled,
  children,
}: {
  onClick: () => void;
  disabled?: boolean;
  children: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className="rounded-lg border border-white/10 bg-white/5 py-1.5 text-[11px] font-medium text-white/80 transition hover:bg-white/10 disabled:opacity-40"
    >
      {children}
    </button>
  );
}
