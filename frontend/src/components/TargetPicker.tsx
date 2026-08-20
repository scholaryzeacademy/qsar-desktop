import { useEffect } from "react";
import { useAppData } from "../lib/AppDataContext";
import { useDownloadGate } from "../lib/useDownloadGate";
import { DownloadGateBar } from "./DownloadGateBar";

interface Option {
  value: string;
  label: string;
}

/** Plain single-target dropdown (no disease browsing) — used by Predict
    and Target Info, which are single-target lookup tools, not part of
    the disease-browsing workflow (see TargetBrowser.tsx for that). */
export function PlainTargetSelect({ targetId, onChange }: { targetId: string; onChange: (id: string) => void }) {
  const { targets } = useAppData();
  const gateApi = useDownloadGate(["model"], onChange);

  const options: Option[] = [
    ...targets.map((t) => ({ value: t.target_id, label: t.target_id })),
    ...gateApi.downloadableExtraIds.map((id) => ({ value: id, label: `${id}${gateApi.downloadHint(id)}` })),
  ];

  useEffect(() => {
    if (!targetId && options.length) {
      const ready = options.find((o) => gateApi.isReady(o.value));
      if (ready) gateApi.select(ready.value);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [options.length]);

  const current = targets.find((t) => t.target_id === targetId);
  const selectValue = gateApi.pendingId ?? targetId;

  return (
    <div>
      <label className="field-label">Target</label>
      <select
        className="field-input"
        value={selectValue}
        onChange={(e) => gateApi.select(e.target.value)}
        disabled={gateApi.gate.active}
      >
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
      <DownloadGateBar gate={gateApi.gate} onRetry={gateApi.retry} />
      <div className="field-hint">
        {current ? (
          <>
            {current.n_compounds ?? "?"} compounds · test R² {current.test_r2 ?? "—"} · RMSE {current.test_rmse ?? "—"}
          </>
        ) : null}
      </div>
    </div>
  );
}
