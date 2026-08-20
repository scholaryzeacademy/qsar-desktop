import type { GateState } from "../lib/useDownloadGate";
import { fmtBytes } from "../lib/format";

export function DownloadGateBar({ gate, onRetry, onStop }: { gate: GateState; onRetry: () => void; onStop?: () => void }) {
  if (gate.error) {
    return (
      <div className="field-hint">
        <span className="text-clay">{gate.error}</span>{" "}
        <button type="button" className="font-semibold text-brand-700 underline" onClick={onRetry}>
          Retry
        </button>
      </div>
    );
  }
  if (!gate.active) return null;
  const pct = gate.total ? Math.round((100 * gate.done) / gate.total) : 0;
  return (
    <div className="mt-1.5">
      <div className="h-1.5 overflow-hidden rounded-full bg-surface2">
        <div className="h-full rounded-full bg-brand-500 transition-all duration-300" style={{ width: `${pct}%` }} />
      </div>
      <div className="mt-1 flex items-center gap-2 text-[11.5px] text-inkmut">
        <span>
          Downloading {gate.kind === "docking" ? "docking data" : "model"}… {pct}%
          {gate.total ? ` (${fmtBytes(gate.done)} of ${fmtBytes(gate.total)})` : ""}
        </span>
        {onStop && gate.jobId && (
          <button type="button" className="font-semibold text-brand-700 underline" onClick={onStop}>
            Stop
          </button>
        )}
      </div>
    </div>
  );
}
