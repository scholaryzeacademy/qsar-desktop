import { Fragment, useState } from "react";
import * as api from "../lib/api";
import { useAppData } from "../lib/AppDataContext";
import { useAdvancedDocking, isGeneOnly } from "../lib/useAdvancedDocking";
import { TargetPicker } from "../components/TargetPicker";
import { DockingModeSection } from "../components/DockingModeSection";
import { AdvancedSettingsPanel } from "../components/AdvancedSettingsPanel";
import { SectionIntro } from "../components/Shell";
import { EmptyState, ErrorBox, Notice } from "../components/Feedback";
import { ConfidenceDot } from "../components/Feedback";
import { DockDetailPanel, EnrichmentChip, FreshDecoyButton } from "../components/DockingPieces";
import type { AdvancedDockingBody, DockResultRow } from "../lib/types";

const DOCK_CONF_COLOR: Record<string, string> = { high: "bg-brand-500", medium: "bg-amber", low: "bg-clay", none: "bg-slateout" };

export function DockingTab() {
  const { dockingStatus, loading } = useAppData();

  if (loading) return null;
  if (!dockingStatus?.ready) return <NotReady />;
  return <DockingReady />;
}

function NotReady() {
  const { dockingStatus } = useAppData();
  const dk = dockingStatus!;
  return (
    <div className="mx-auto max-w-[720px] py-6 text-center">
      <div className="mb-2 text-[40px] opacity-25">⚙</div>
      <h2 className="font-display text-[19px] font-medium text-ink">Docking — not yet enabled on this machine</h2>
      <p className="mt-1 text-[13px] text-inkmut">{dk.note}</p>
      <div className="mt-6 text-left">
        <h5 className="mb-1.5 text-[11px] font-bold uppercase tracking-wide text-brand-700">Python packages</h5>
        {Object.entries(dk.packages || {}).map(([n, ok]) => (
          <CheckLine key={n} ok={ok} name={n} desc={dk.package_desc?.[n]} />
        ))}
        <h5 className="mb-1.5 mt-4 text-[11px] font-bold uppercase tracking-wide text-brand-700">Engine binaries</h5>
        {Object.entries(dk.binaries || {}).map(([n, ok]) => (
          <CheckLine key={n} ok={ok} name={n} desc={dk.binary_desc?.[n]} />
        ))}
        <Notice>Install the missing items, prepare receptor profiles, then this tab activates automatically.</Notice>
        <h5 className="mb-1.5 mt-4 text-[11px] font-bold uppercase tracking-wide text-brand-700">Planned pipeline</h5>
        <ul className="list-disc pl-5 text-[13px] text-inkmut">
          {(dk.planned || []).map((p, i) => (
            <li key={i}>{p}</li>
          ))}
        </ul>
      </div>
    </div>
  );
}

function CheckLine({ ok, name, desc }: { ok: boolean; name: string; desc?: string }) {
  return (
    <div className="flex items-center gap-2 py-[3px] text-[13px]">
      <span className={`dot ${ok ? "bg-brand-500" : "bg-slateout"}`} />
      <b className="min-w-[150px]">{name}</b>
      <span className="text-inkmut">{desc || ""}</span>
    </div>
  );
}

function DockingReady() {
  const { dockingStatus } = useAppData();
  const [targetId, setTargetId] = useState("");
  const adv = useAdvancedDocking(targetId);
  const dockDetail = dockingStatus?.target_details?.find((d: any) => d.target_id === targetId) ?? null;
  const [smiles, setSmiles] = useState("");
  const [state, setState] = useState<"idle" | "submitting" | "polling" | "error" | "done">("idle");
  const [error, setError] = useState("");
  const [caveat, setCaveat] = useState<string | null>(null);
  const [results, setResults] = useState<DockResultRow[] | null>(null);
  const [receptorPdbPath, setReceptorPdbPath] = useState<string | null>(null);
  const [progress, setProgress] = useState<{ done: number; total: number } | null>(null);

  const run = async () => {
    setError("");
    const smilesList = smiles
      .split("\n")
      .map((s) => s.trim())
      .filter(Boolean);
    if (!targetId) {
      setError("Pick a target.");
      setState("error");
      return;
    }
    if (!smilesList.length) {
      setError("Enter SMILES.");
      setState("error");
      return;
    }
    const advBody = adv.getAdvanced();
    if (isGeneOnly(targetId) && !advBody?.custom_profile && !adv.site) {
      setError('Pick a structure in Advanced Settings first — there\'s no automatic default for this target yet. Try "Find best validated structure automatically" there, or pick one manually.');
      setState("error");
      return;
    }
    setState("submitting");
    try {
      const r = await api.submitDocking(targetId, smilesList, advBody);
      setCaveat(r.caveat || null);
      setState("polling");
      while (true) {
        await api.sleep(2000);
        const s = await api.pollRetry(() => api.dockingJob(r.job_id));
        if (s.status === "done") {
          setResults(s.results);
          setReceptorPdbPath(s.receptor_pdb_path || null);
          setState("done");
          return;
        }
        if (s.status === "error") {
          setError(s.error || "failed");
          setState("error");
          return;
        }
        setProgress({ done: s.done, total: s.total });
      }
    } catch (e: any) {
      setError(e.message || "Error");
      setState("error");
    }
  };

  return (
    <div className="mx-auto grid max-w-[1280px] grid-cols-1 items-start gap-5 lg:grid-cols-[350px_1fr]">
      <aside className="card sticky top-[78px] max-h-[calc(100vh-96px)] overflow-y-auto p-[18px]">
        <SectionIntro title="Structure-based docking" sub="AutoDock Vina + PoseBusters physical-validity gate." />
        <TargetPicker targetId={targetId} onChange={setTargetId} need={["docking"]} />
        <div className="mt-3">
          <DockingModeSection adv={adv} targetId={targetId} />
        </div>
        <label className="field-label" style={{ marginTop: 12 }}>
          SMILES (one per line)
        </label>
        <textarea className="field-input min-h-[100px] resize-y font-mono text-[12.5px]" value={smiles} onChange={(e) => setSmiles(e.target.value)} />
        <AdvancedSettingsPanel key={targetId} adv={adv} openByDefault={!!targetId} validated={dockDetail?.validated ?? null} />
        <button className="btn-primary mt-[18px]" onClick={run} disabled={state === "submitting" || state === "polling" || adv.preparingStructure}>
          {adv.preparingStructure ? "Preparing structure…" : "Dock compounds"}
        </button>
      </aside>
      <main className="card min-h-[60vh] overflow-hidden">
        {state === "idle" && <EmptyState title="Dock your compounds" hint="Pick a target, paste SMILES, and run AutoDock Vina against its validated pocket." />}
        {(state === "submitting" || state === "polling") && (
          <div className="px-8 py-16 text-center text-inkmut">
            {caveat && <Notice>{caveat}</Notice>}
            {state === "submitting" ? "Submitting…" : progress ? `Docking ${progress.done}/${progress.total}… (minutes per compound)` : "Working…"}
          </div>
        )}
        {state === "error" && (
          <>
            {caveat && <Notice>{caveat}</Notice>}
            <ErrorBox message={error} />
          </>
        )}
        {state === "done" && results && (
          <DockResultsTable results={results} caveat={caveat} receptorPdbPath={receptorPdbPath} targetId={targetId} advanced={adv.getAdvanced()} />
        )}
      </main>
    </div>
  );
}

function DockResultsTable({
  results,
  caveat,
  receptorPdbPath,
  targetId,
  advanced,
}: {
  results: DockResultRow[];
  caveat: string | null;
  receptorPdbPath: string | null;
  targetId: string;
  advanced: AdvancedDockingBody | null;
}) {
  const [openRows, setOpenRows] = useState<Set<number>>(new Set());
  const toggle = (i: number) =>
    setOpenRows((s) => {
      const n = new Set(s);
      n.has(i) ? n.delete(i) : n.add(i);
      return n;
    });
  const hasGnina = results.some((r) => r.gnina?.cnn_score != null);
  const hasEnrichment = results.some((r) => r.enrichment_percentile != null);

  return (
    <div>
      {caveat && <Notice>{caveat}</Notice>}
      <div className="max-h-[calc(100vh-260px)] overflow-y-auto overflow-x-hidden">
        <table className="w-full table-fixed border-collapse text-[13px]">
          <thead>
            <tr>
              {[
                { h: "", w: "w-6" },
                { h: "Compound" },
                { h: "Confidence", w: "w-24" },
                { h: "Vina (kcal/mol)", w: "w-20" },
                ...(hasGnina ? [{ h: "GNINA CNN", w: "w-20" }, { h: "GNINA affinity", w: "w-20" }, { h: "GNINA (kcal/mol)", w: "w-20" }] : []),
                ...(hasEnrichment ? [{ h: "Enrichment", w: "w-24" }] : []),
                { h: "Status", w: "w-28" },
                { h: "Fresh decoy check", w: "w-32" },
              ].map((c, i) => (
                <th key={i} className={`sticky top-0 z-10 border-b border-line bg-surface2 px-2.5 py-2.5 text-left text-[10.5px] font-semibold uppercase tracking-wide text-inkmut ${c.w || ""}`}>
                  {c.h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {results.map((r, i) => {
              const canView = !!r.interaction_png;
              const hasDetail = canView || r.status === "ok";
              const open = openRows.has(i);
              return (
                <Fragment key={i}>
                  <tr className={hasDetail ? "cursor-pointer hover:bg-canvas" : ""} onClick={() => hasDetail && toggle(i)}>
                    <td className="border-b border-surface2 px-2.5 py-2.5 text-brand-600">{hasDetail ? (open ? "▾" : "▸") : ""}</td>
                    <td className="smi-mono border-b border-surface2 px-2.5 py-2.5">{r.smiles}</td>
                    <td className="border-b border-surface2 px-2.5 py-2.5">
                      <span className="chip min-w-0 max-w-full">
                        <ConfidenceDot level={r.confidence} />
                        <span className="min-w-0 truncate">{r.confidence || "—"}</span>
                      </span>
                    </td>
                    <td className="border-b border-surface2 px-2.5 py-2.5">{r.vina_score ?? "—"}</td>
                    {hasGnina && (
                      <>
                        <td className="border-b border-surface2 px-2.5 py-2.5">{r.gnina?.cnn_score ?? "—"}</td>
                        <td className="border-b border-surface2 px-2.5 py-2.5">{r.gnina?.cnn_affinity ?? "—"}</td>
                        <td className="border-b border-surface2 px-2.5 py-2.5">{r.gnina?.gnina_affinity ?? "—"}</td>
                      </>
                    )}
                    {hasEnrichment && (
                      <td className="border-b border-surface2 px-2.5 py-2.5">
                        <EnrichmentChip r={r} />
                      </td>
                    )}
                    <td className="truncate border-b border-surface2 px-2.5 py-2.5 text-inkmut" title={r.status === "ok" ? `${r.n_valid} valid pose(s)` : r.reason || r.status}>
                      {r.status === "ok" ? `${r.n_valid} valid pose(s)` : r.reason || r.status}
                    </td>
                    <td className="border-b border-surface2 px-2.5 py-2.5">
                      {r.status === "ok" ? <FreshDecoyButton smiles={r.smiles} targetId={targetId} advanced={advanced} /> : <span className="text-inkmut">—</span>}
                    </td>
                  </tr>
                  {hasDetail && open && (
                    <tr>
                      <td className="border-b border-surface2" />
                      <td colSpan={20} className="border-b border-surface2 p-0">
                        <DockDetailPanel r={r} receptorPdbPath={receptorPdbPath} />
                      </td>
                    </tr>
                  )}
                </Fragment>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
