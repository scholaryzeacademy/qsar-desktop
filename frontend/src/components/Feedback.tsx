import { LeafLattice } from "./Icons";

export function EmptyState({ title, hint }: { title: string; hint?: string }) {
  return (
    <div className="relative flex flex-col items-center justify-center gap-3 overflow-hidden px-8 py-20 text-center">
      <LeafLattice className="h-12 w-12 text-brand-300" />
      <div className="font-display text-[19px] font-medium text-ink">{title}</div>
      {hint && <p className="max-w-sm text-[13px] text-inkmut">{hint}</p>}
    </div>
  );
}

export function ErrorBox({ message }: { message: string }) {
  return (
    <div className="m-4 rounded-xl border border-clay/30 bg-clay/10 px-4 py-2.5 text-[13px] font-medium text-clay">
      {message}
    </div>
  );
}

export function Notice({ children, tone = "amber" }: { children: React.ReactNode; tone?: "amber" | "brand" }) {
  const cls =
    tone === "brand"
      ? "border-brand-300/60 bg-brand-50 text-brand-800 bg-brand-500/10"
      : "border-amber/30 bg-amber/10 text-amber";
  return <div className={`m-4 rounded-xl border px-3.5 py-2.5 text-[12.5px] ${cls}`}>{children}</div>;
}

export function Disclaimer({ children }: { children: React.ReactNode }) {
  return (
    <div className="m-4 rounded-xl border border-brand-300/50 bg-brand-500/[0.07] px-3.5 py-2.5 text-[12.5px] text-brand-800">
      {children}
    </div>
  );
}

export function Spinner({ label = "Working…" }: { label?: string }) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 px-10 py-16 text-inkmut">
      <LeafLattice className="h-9 w-9 text-brand-500" spin />
      <div className="text-[13px]">{label}</div>
    </div>
  );
}

export function ProgressBar({ pct, label }: { pct: number; label?: string }) {
  return (
    <div className="mx-auto max-w-sm px-8 py-16 text-center">
      {label && <div className="mb-2 text-[13px] text-inkmut">{label}</div>}
      <div className="h-2 overflow-hidden rounded-full bg-surface2">
        <div className="h-full rounded-full bg-brand-500 transition-all duration-300" style={{ width: `${pct}%` }} />
      </div>
      <div className="mt-1.5 text-[12px] text-inkmut">{pct}%</div>
    </div>
  );
}

const CONFIDENCE_COLOR: Record<string, string> = {
  high: "bg-brand-500",
  med: "bg-amber",
  medium: "bg-amber",
  low: "bg-clay",
  out: "bg-slateout",
  na: "bg-slateout",
  none: "bg-slateout",
};

export function ConfidenceDot({ level }: { level?: string | null }) {
  return <span className={`dot ${CONFIDENCE_COLOR[level || "na"] || "bg-slateout"}`} />;
}

export function Badge({ ok, children }: { ok: boolean; children: React.ReactNode }) {
  return (
    <span className={`badge ${ok ? "bg-brand-500/15 text-brand-800" : "bg-amber/15 text-amber"}`}>{children}</span>
  );
}
