import { useEffect, useState } from "react";
import * as api from "../lib/api";
import { PlainTargetSelect } from "../components/TargetPicker";
import { SectionIntro, ResultHeader, ResultName, Stat } from "../components/Shell";
import { EmptyState, ErrorBox, Notice, Spinner } from "../components/Feedback";
import { ValidationPanel } from "../components/ValidationPanel";
import type { BucketFile } from "../lib/types";

export function TargetInfoTab() {
  const [targetId, setTargetId] = useState("");
  const [state, setState] = useState<"idle" | "loading" | "error" | "done">("idle");
  const [error, setError] = useState("");
  const [metrics, setMetrics] = useState<Record<string, any>>({});
  const [files, setFiles] = useState<BucketFile[]>([]);
  const [dockDetail, setDockDetail] = useState<any>(null);

  useEffect(() => {
    if (!targetId) return;
    let cancelled = false;
    setState("loading");
    (async () => {
      try {
        const [m, b, dock] = await Promise.all([
          api.factoryMetrics(targetId),
          api.factoryBucket(targetId),
          api.dockingStatus().catch(() => ({ target_details: [] } as any)),
        ]);
        if (cancelled) return;
        setMetrics(m.metrics || {});
        setFiles(b.files || []);
        setDockDetail((dock.target_details || []).find((d: any) => d.target_id === targetId) || null);
        setState("done");
      } catch (e: any) {
        if (!cancelled) {
          setError(e.message || "Error");
          setState("error");
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [targetId]);

  const plots = files.filter((f) => f.category === "Plots");
  const cleaned = files.find((f) => f.path === "Data/full_cleaned.csv");
  const m = metrics;

  return (
    <div className="mx-auto grid max-w-[1280px] grid-cols-1 items-start gap-5 lg:grid-cols-[350px_1fr]">
      <aside className="card sticky top-[78px] max-h-[calc(100vh-96px)] overflow-y-auto p-[18px]">
        <SectionIntro title="Target Info" sub="Validation evidence & full bucket browser for one target." />
        <PlainTargetSelect targetId={targetId} onChange={setTargetId} />
      </aside>
      <main className="card min-h-[60vh] overflow-hidden">
        {state === "idle" && <EmptyState title="Inspect a target's evidence" hint="Pick a target to see its validation evidence and files." />}
        {state === "loading" && <Spinner />}
        {state === "error" && <ErrorBox message={error} />}
        {state === "done" && (
          <div>
            <ResultHeader>
              <ResultName>{targetId}</ResultName>
              <Stat label="Best model">{m.Best_Model || m.best_model || "—"}</Stat>
              <Stat label="Tropsha">{m.Tropsha_Pass === true ? "pass" : m.Tropsha_Pass === false ? "fail" : "—"}</Stat>
              <Stat label="Docking">{dockDetail ? (dockDetail.validated ? "VALIDATED" : "UNVALIDATED") : "n/a"}</Stat>
            </ResultHeader>
            <div className="grid grid-cols-2 gap-2.5 p-5 sm:grid-cols-3">
              {[
                ["Test R²", m.R2_Test ?? "—"],
                ["Test RMSE", m.RMSE_Test ?? "—"],
                ["Pearson r", m.Pearson_r ?? "—"],
                ["AD coverage", m.AD_Coverage_pct != null ? `${m.AD_Coverage_pct}%` : "—"],
                ["Y-random ΔR²", m.Y_Random_DeltaR2 ?? "—"],
                ["Compounds (fit/test)", `${m.Fit_N ?? "?"}/${m.Test_N ?? "?"}`],
              ].map(([l, v]) => (
                <div key={l as string} className="rounded-lg border border-line bg-surface2/50 px-3 py-2.5">
                  <div className="text-[10.5px] font-semibold uppercase tracking-wide text-inkmut">{l}</div>
                  <div className="mt-0.5 text-[16px] font-semibold text-ink">{v as any}</div>
                </div>
              ))}
            </div>
            {!Object.keys(m).length && <Notice>No metrics file found for this target's bucket.</Notice>}
            {dockDetail && (
              <div className="px-5 pb-1">
                <ValidationPanel details={[dockDetail]} />
              </div>
            )}
            {!!plots.length && (
              <>
                <div className="px-5 pb-1 pt-2 text-[10.5px] font-bold uppercase tracking-wide text-brand-700">QSAR validation plots</div>
                <div className="grid grid-cols-1 gap-3 px-5 pb-5 sm:grid-cols-2 lg:grid-cols-3">
                  {plots.map((f) => (
                    <figure key={f.path} className="m-0 overflow-hidden rounded-xl border border-line bg-surface">
                      <img loading="lazy" src={api.apiUrl(`/api/factory/download/${targetId}?path=${encodeURIComponent(f.path)}`)} className="block w-full" />
                      <figcaption className="px-2.5 py-2 text-[11.5px] text-inkmut">{f.annotation || f.name}</figcaption>
                    </figure>
                  ))}
                </div>
              </>
            )}
            {cleaned && (
              <>
                <div className="px-5 pb-1 pt-1 text-[10.5px] font-bold uppercase tracking-wide text-brand-700">Cleaned dataset</div>
                <div className="mx-5 mb-5 flex items-center justify-between rounded-lg border border-line px-3 py-2.5 text-[12.5px]">
                  <div>
                    <span className="font-mono">{cleaned.path}</span>
                    <div className="text-[11.5px] text-inkmut">{cleaned.annotation || ""}</div>
                  </div>
                  <a className="btn-link" href={api.apiUrl(`/api/factory/download/${targetId}?path=${encodeURIComponent(cleaned.path)}`)} download>
                    {(cleaned.bytes / 1024).toFixed(0)} KB
                  </a>
                </div>
              </>
            )}
          </div>
        )}
      </main>
    </div>
  );
}
