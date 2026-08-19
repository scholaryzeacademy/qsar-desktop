import { useEffect } from "react";
import { createPortal } from "react-dom";

export function Modal({
  title,
  sub,
  onClose,
  children,
  wide = true,
}: {
  title: React.ReactNode;
  sub?: React.ReactNode;
  onClose: () => void;
  children: React.ReactNode;
  wide?: boolean;
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  return createPortal(
    <div
      className="fixed inset-0 z-[1000] flex items-center justify-center bg-brand-950/55 p-6 backdrop-blur-[2px]"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        className={`flex ${wide ? "w-[min(1100px,94vw)] h-[min(760px,88vh)]" : "w-[min(560px,94vw)] max-h-[88vh]"} flex-col overflow-hidden rounded-2xl bg-surface shadow-pop animate-riseIn`}
      >
        <div className="flex shrink-0 items-center gap-2.5 border-b border-line px-5 py-3.5">
          <div className="flex-1">
            <h3 className="text-[15px] font-semibold text-ink">{title}</h3>
            {sub && <p className="mt-0.5 text-[12px] text-inkmut">{sub}</p>}
          </div>
          <button
            onClick={onClose}
            aria-label="Close"
            className="rounded-lg px-2.5 py-1.5 text-inkmut transition hover:bg-surface2 hover:text-ink"
          >
            <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M18 6L6 18M6 6l12 12" strokeLinecap="round" />
            </svg>
          </button>
        </div>
        <div className="flex-1 overflow-auto">{children}</div>
      </div>
    </div>,
    document.body
  );
}
