"use client";

import { useEffect, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";

interface Props {
  open: boolean;
  onClose: () => void;
  title: string;
  icon?: ReactNode;
  headerRight?: ReactNode;
  children: ReactNode;
  widthClass?: string;
}

// 상세 정보를 오버레이로 표시. document.body 로 portal 하여 어떤 카드(특히
// backdrop-blur 로 containing block 이 생기는 fm-card) 위에도 최상단에 뜬다.
// ESC/배경 클릭으로 닫힘. 페이지 높이를 늘리지 않는다.
export function Modal({
  open,
  onClose,
  title,
  icon,
  headerRight,
  children,
  widthClass = "max-w-lg",
}: Props) {
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = "";
    };
  }, [open, onClose]);

  if (!open || !mounted) return null;

  const content = (
    <div className="fixed inset-0 z-[1000] grid place-items-center p-4">
      <div
        className="absolute inset-0 bg-black/65 backdrop-blur-sm"
        onClick={onClose}
      />
      <div
        className={`relative w-full ${widthClass} max-h-[90vh] overflow-y-auto rounded-2xl border border-white/10 bg-ink-700 p-5 shadow-2xl`}
        role="dialog"
        aria-modal="true"
      >
        <div className="mb-3 flex items-center gap-2">
          <h3 className="flex items-center gap-2 text-base font-bold">
            {icon}
            {title}
          </h3>
          {headerRight}
          <button
            onClick={onClose}
            className="ml-auto text-white/40 transition hover:text-white/90"
            aria-label="닫기"
          >
            ✕
          </button>
        </div>
        {children}
      </div>
    </div>
  );

  return createPortal(content, document.body);
}
