"use client";

import { useEffect, useState } from "react";

import type { IngredientEntry } from "@/lib/api/types";

import { Modal } from "./Modal";

const EMOJI: Record<string, string> = {
  닭가슴살: "🍗",
  계란: "🥚",
  브로콜리: "🥦",
  두부: "🧈",
  그릭요거트: "🥛",
};

interface Props {
  open: boolean;
  name: string; // Enter 로 넘어온 재료명
  onCancel: () => void;
  onAdd: (entry: IngredientEntry) => void;
}

// 재료 상세 입력 팝업: 용량/수량 + 유통기한 + 보관방법 → 팬트리에 추가.
export function IngredientDetailModal({ open, name, onCancel, onAdd }: Props) {
  const [amount, setAmount] = useState("");
  const [expirationDate, setExpirationDate] = useState("");
  const [storageType, setStorageType] = useState("냉장 보관");

  // 팝업이 새로 열릴 때마다 입력 초기화.
  useEffect(() => {
    if (open) {
      setAmount("");
      setExpirationDate("");
      setStorageType("냉장 보관");
    }
  }, [open, name]);

  function submit() {
    onAdd({
      name,
      amount: amount.trim() || undefined,
      expirationDate: expirationDate || undefined,
      storageType: storageType || undefined,
    });
  }

  return (
    <Modal open={open} onClose={onCancel} title="재료 상세 입력">
      <p className="mb-3 text-xs text-white/50">
        입력한 용량과 유통기한 정보는 Pantry 분석에 반영됩니다.
      </p>

      <div className="mb-4 flex items-center gap-3 rounded-xl bg-white/[0.04] px-4 py-3">
        <span className="text-2xl">{EMOJI[name] ?? "🍽️"}</span>
        <span className="text-lg font-bold">{name}</span>
        <span className="ml-auto rounded-md bg-lime-accent/15 px-2 py-0.5 text-[11px] text-lime-accent">
          {storageType}
        </span>
      </div>

      <div className="grid grid-cols-2 gap-3">
        <label className="block">
          <span className="mb-1 block text-xs text-white/55">용량 / 수량</span>
          <input
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && submit()}
            placeholder="예: 300g"
            autoFocus
            className={inputCls}
          />
        </label>
        <label className="block">
          <span className="mb-1 block text-xs text-white/55">유통기한</span>
          <input
            type="date"
            value={expirationDate}
            onChange={(e) => setExpirationDate(e.target.value)}
            className={inputCls}
          />
        </label>
      </div>

      <label className="mt-3 block">
        <span className="mb-1 block text-xs text-white/55">보관 방법</span>
        <select
          value={storageType}
          onChange={(e) => setStorageType(e.target.value)}
          className={inputCls}
        >
          <option>냉장 보관</option>
          <option>냉동 보관</option>
          <option>실온 보관</option>
        </select>
      </label>

      <p className="mt-3 text-[11px] text-white/40">
        예: 300g, 1개, 2팩 / 달력에서 유통기한을 선택하세요.
      </p>

      <div className="mt-4 flex gap-2">
        <button
          onClick={submit}
          className="flex-1 rounded-xl bg-lime-accent py-2.5 text-sm font-bold text-ink-900 transition hover:brightness-105"
        >
          팬트리에 추가
        </button>
        <button
          onClick={onCancel}
          className="rounded-xl border border-white/10 bg-white/5 px-4 py-2.5 text-sm text-white/70 transition hover:bg-white/10"
        >
          취소
        </button>
      </div>
    </Modal>
  );
}

const inputCls =
  "w-full rounded-lg border border-white/10 bg-black/20 px-3 py-2 text-sm outline-none placeholder:text-white/30 focus:border-lime-accent/60 [color-scheme:dark]";
