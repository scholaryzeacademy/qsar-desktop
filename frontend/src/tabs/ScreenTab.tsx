import { Fragment, useState } from "react";
import * as api from "../lib/api";
import { useAppData } from "../lib/AppDataContext";
import { useAdvancedDocking, isGeneOnly } from "../lib/useAdvancedDocking";
import { useMoleculeInput } from "../lib/useMoleculeInput";
import { MoleculeInputPanel } from "../components/MoleculeInputPanel";
import { TargetBrowser } from "../components/TargetBrowser";
import { DockingModeSection } from "../components/DockingModeSection";
import { AdvancedSettingsPanel } from "../components/AdvancedSettingsPanel";
import { WhyThisButton } from "../components/RecommendationPanel";
import { SectionIntro, ResultHeader, ResultName, Stat } from "../components/Shell";
import { ConfidenceDot, Disclaimer, EmptyState, ErrorBox, Notice } from "../components/Feedback";
import { LeafLattice } from "../components/Icons";
import { DownloadComplexButton, EnrichmentChip, FreshDecoyButton } from "../components/DockingPieces";
import { tierClass } from "../lib/tierClass";
import type { AdvancedDockingBody, DockResultRow, ScreenResult } from "../lib/types";

const SCREEN_STEPS = [
  "Parse & standardise SMILES",
  "Featurise (RDKit 2D + MACCS + Morgan)",
  "Applicability-domain check",
  "QSAR potency prediction",
  "ADMET profiling",
  "Docking",
  "Rank & fuse evidence",
  "Finalise & export",
];

type FlowState =
  | { kind: "idle" }
  | { kind: "steps"; step: number; note: string }
  | { kind: "dock-submit" }
  | { kind: "dock-poll"; done: number; total: number; caveat: string | null }
  | { kind: "error"; message: string }
  | { kind: "screen-done"; result: ScreenResult; jobId: string; targetId: string; advanced: AdvancedDockingBody | null }
  | { kind: "dock-done"; results: DockResultRow[]; receptorPdbPath: string | null; targetId: string; advanced: AdvancedDockingBody | null; caveat: string | null };

export function ScreenTab() {
  const { dockingStatus } = useAppData();
  const [targetId, setTargetId] = useState("");
  const adv = useAdvancedDocking(targetId);
  const mol = useMoleculeInput();
  const [flow, setFlow] = useState<FlowState>({ kind: "idle" });
  const geneOnly = isGeneOnly(targetId);
  const dockDetail = dockingStatus?.target_details?.find((d: any) => d.target_id === targetId) ?? null;

  const run = async () => {
    try {
      const smiles = await mol.resolve();
      if (!smiles.length) throw new Error("Enter at least one SMILES.");
      if (!targetId) throw new Error("Pick a target.");

      const advBody = adv.getAdvanced();

      if (geneOnly) {
        if (!advBody?.custom_profile && !adv.site) {
          throw new Error('Pick a structure in Advanced Settings first — there\'s no automatic default for this target yet. Try "Find best validated structure automatically" there, or pick one manually.');
        }
        setFlow({ kind: "dock-submit" });
        const r = await api.submitDocking(targetId, smiles, advBody);
        setFlow({ kind: "dock-poll", done: 0, total: r.total, caveat: r.caveat || null });
        while (true) {
          await api.sleep(2000);
          const s = await api.pollRetry(() => api.dockingJob(r.job_id));
          if (s.status === "done") {
            setFlow({ kind: "dock-done", results: s.results, receptorPdbPath: s.receptor_pdb_path || null, targetId, advanced: advBody, caveat: r.caveat || null });
            return;
          }
          if (s.status === "error") throw new Error(s.error || "failed");
          setFlow({ kind: "dock-poll", done: s.done, total: s.total, caveat: r.caveat || null });
        }
      }

      setFlow({ kind: "steps", step: 0, note: "Submitting…" });
      const r = await api.submitScreen(targetId, smiles, advBody);
      while (true) {
        const s = await api.pollRetry(() => api.screenJob(r.job_id));
        if (s.status === "error") throw new Error(s.error || "Screen failed.");
        if (s.status === "done" && s.result) {
          setFlow({ kind: "screen-done", result: s.result, jobId: r.job_id, targetId, advanced: advBody });
          return;
        }
        const note = s.step === 6 && s.total ? `Docking ${s.done || 0}/${s.total}…` : s.step_label || "Working…";
        setFlow({ kind: "steps", step: s.step || 0, note });
        await api.sleep(900);
      }
    } catch (e: any) {
      setFlow({ kind: "error", message: e.message || "Error" });
    }
  };

  return (
    <div className="mx-auto grid max-w-[1280px] grid-cols-1 items-start gap-5 lg:grid-cols-[350px_1fr]">
      <aside className="card sticky top-[78px] max-h-[calc(100vh-96px)] overflow-y-auto p-[18px]">
        <SectionIntro title="Screen compounds" sub="Full pipeline: parse → featurise → AD → QSAR → ADMET → docking → ranked shortlist." />
        <TargetBrowser targetId={targetId} onChange={setTargetId} need={["model", "docking"]} adv={adv} />
        {!geneOnly && <WhyThisButton targetId={targetId} key={targetId} />}
        <div className="mt-3">
          <DockingModeSection adv={adv} targetId={targetId} />
        </div>
        <div className="mt-3">
          <MoleculeInputPanel state={mol} />
        </div>
        <AdvancedSettingsPanel key={targetId} adv={adv} openByDefault={!!targetId} validated={dockDetail?.validated ?? null} />
        <button
          className="btn-primary mt-[18px]"
          onClick={run}
          disabled={flow.kind === "steps" || flow.kind === "dock-submit" || flow.kind === "dock-poll" || adv.preparingStructure}
        >
          {adv.preparingStructure ? "Preparing structure…" : geneOnly ? "Dock this target (no QSAR model)" : "Run screen"}
        </button>
      </aside>
      <main className="card min-h-[60vh] overflow-hidden">
        {flow.kind === "idle" && <EmptyState title="Run the full pipeline" hint="Select a target and enter molecules to run the full 8-step pipeline." />}
        {flow.kind === "steps" && <StepsView step={flow.step} note={flow.note} />}
        {(flow.kind === "dock-submit" || flow.kind === "dock-poll") && (
          <div className="px-8 py-16 text-center text-inkmut">
            {flow.kind === "dock-poll" && flow.caveat && <Notice>{flow.caveat}</Notice>}
            {flow.kind === "dock-submit" ? "Submitting…" : `Docking ${flow.done}/${flow.total}… (minutes per compound)`}
          </div>
        )}
        {flow.kind === "error" && <ErrorBox message={flow.message} />}
        {flow.kind === "screen-done" && <ScreenResults d={flow.result} jobId={flow.jobId} advanced={flow.advanced} />}
        {flow.kind === "dock-done" && <GeneOnlyDockResults results={flow.results} receptorPdbPath={flow.receptorPdbPath} targetId={flow.targetId} advanced={flow.advanced} caveat={flow.caveat} />}
      </main>
    </div>
  );
}

function StepsView({ step, note }: { step: number; note: string }) {
  return (
    <div className="mx-auto flex max-w-[460px] flex-col gap-1.5 py-8">
      <div className="mb-1.5 flex flex-col items-center gap-2 text-center text-[12.5px] text-inkmut">
        <LeafLattice className="h-7 w-7 text-brand-500" spin />
        Step {step}/8 — {note}
      </div>
      {SCREEN_STEPS.map((label, i) => {
        const n = i + 1;
        const done = n < step;
        const on = n === step;
        return (
          <div key={label} className={`flex items-center gap-2.5 rounded-lg px-2.5 py-1.5 text-[13px] ${on ? "bg-brand-500/[0.08]" : ""}`}>
            <span
              className={`flex h-[22px] w-[22px] shrink-0 items-center justify-center rounded-full text-[11px] font-bold ${
                done ? "bg-brand-500 text-white" : on ? "bg-brand-700 text-white" : "bg-surface2 text-inkmut"
              }`}
            >
              {done ? "✓" : n}
            </span>
            <span>{label}</span>
          </div>
        );
      })}
    </div>
  );
}

function ScreenResults({ d, jobId, advanced }: { d: ScreenResult; jobId: string; advanced: AdvancedDockingBody | null }) {
  const [openRows, setOpenRows] = useState<Set<number>>(new Set());
  const toggle = (i: number) =>
    setOpenRows((s) => {
      const n = new Set(s);
      n.has(i) ? n.delete(i) : n.add(i);
      return n;
    });
  const c = d.counts;
  const hasEnrichment = d.shortlist.some((r) => r.docking?.enrichment_percentile != null);

  return (
    <div>
      <ResultHeader>
        <ResultName>{d.target_id}</ResultName>
        <Stat label="Submitted">{c.submitted}</Stat>
        <Stat label="Parsed">{c.parsed}</Stat>
        <Stat label="Skipped">{c.skipped}</Stat>
        <Stat label="Docking">{d.docking_used ? "used" : "skipped"}</Stat>
      </ResultHeader>
      <Disclaimer>{d.methods_note}</Disclaimer>
      {d.docking_note && !d.docking_used && <Notice>{d.docking_note}</Notice>}
      {!d.shortlist.length ? (
        <div className="px-8 py-16 text-center text-inkmut">No molecules could be parsed.</div>
      ) : (
        <>
          <div className="max-h-[calc(100vh-320px)] overflow-y-auto overflow-x-hidden">
            <table className="w-full table-fixed border-collapse text-[13px]">
              <thead>
                <tr>
                  {[
                    { h: "#", w: "w-9" },
                    { h: "Compound" },
                    { h: "QSAR pIC50", w: "w-20" },
                    { h: "Confidence", w: "w-24" },
                    ...(d.docking_used ? [{ h: "Vina", w: "w-16" }, { h: "Dock conf.", w: "w-20" }] : []),
                    ...(hasEnrichment ? [{ h: "Enrichment", w: "w-24" }] : []),
                    { h: "Fused", w: "w-16" },
                    { h: "Caveats", w: "w-32" },
                    { h: "Fresh decoy check", w: "w-32" },
                  ].map((c, i) => (
                    <th key={i} className={`sticky top-0 z-10 border-b border-line bg-surface2 px-2.5 py-2.5 text-left text-[10.5px] font-semibold uppercase tracking-wide text-inkmut ${c.w || ""}`}>
                      {c.h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {d.shortlist.map((r, i) => {
                  const canView = !!(r.docking && r.docking.interaction_png);
                  const canFreshDecoy = !!(r.docking && r.docking.status === "ok");
                  const open = openRows.has(i);
                  return (
                    <Fragment key={i}>
                      <tr className={canView ? "cursor-pointer hover:bg-canvas" : ""} onClick={() => canView && toggle(i)}>
                        <td className="border-b border-surface2 px-2.5 py-2.5 text-brand-600">
                          {r.rank}
                          {canView ? (open ? " ▾" : " ▸") : ""}
                        </td>
                        <td className="smi-mono border-b border-surface2 px-2.5 py-2.5">{r.smiles}</td>
                        <td className="border-b border-surface2 px-2.5 py-2.5">
                          {r.qsar.in_domain ? <b>{r.qsar.predicted_pIC50}</b> : <span className="text-inkmut">out-of-domain</span>}
                        </td>
                        <td className="border-b border-surface2 px-2.5 py-2.5">
                          <span className="chip min-w-0 max-w-full" title={r.qsar.confidence_label}>
                            <span className={`dot shrink-0 ${tierClass(r.qsar.confidence)}`} />
                            <span className="min-w-0 truncate">{r.qsar.confidence_label}</span>
                          </span>
                        </td>
                        {d.docking_used && (
                          <>
                            <td className="border-b border-surface2 px-2.5 py-2.5">{r.docking ? r.docking.vina_score ?? "—" : "—"}</td>
                            <td className="border-b border-surface2 px-2.5 py-2.5">{r.docking ? r.docking.confidence ?? "—" : "—"}</td>
                          </>
                        )}
                        {hasEnrichment && (
                          <td className="border-b border-surface2 px-2.5 py-2.5">
                            <EnrichmentChip r={r.docking || {}} />
                          </td>
                        )}
                        <td className="border-b border-surface2 px-2.5 py-2.5">{r.fused_score ?? "—"}</td>
                        <td className="border-b border-surface2 px-2.5 py-2.5">
                          {r.caveats.length ? r.caveats.map((c, j) => (
                            <span key={j} className="mb-0.5 block text-[11px] leading-snug text-amber">
                              {c}
                            </span>
                          )) : "—"}
                        </td>
                        <td className="border-b border-surface2 px-2.5 py-2.5">
                          {canFreshDecoy ? <FreshDecoyButton smiles={r.smiles} targetId={d.target_id} advanced={advanced} /> : <span className="text-inkmut">—</span>}
                        </td>
                      </tr>
                      {canView && open && (
                        <tr>
                          <td className="border-b border-surface2" />
                          <td colSpan={20} className="border-b border-surface2 bg-surface2/40 p-0">
                            <div className="px-5 py-3.5">
                              <img src={`data:image/png;base64,${r.docking!.interaction_png}`} className="max-w-full rounded-lg border border-line bg-white" />
                              {r.docking!.pose_pdb && (
                                <div className="mt-2">
                                  <DownloadComplexButton smiles={r.smiles} posePdb={r.docking!.pose_pdb} receptorPdbPath={d.receptor_pdb_path} />
                                </div>
                              )}
                            </div>
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>
          <div className="flex items-center justify-between border-t border-line px-5 py-2.5">
            <span className="text-[12.5px] text-inkmut">{d.skipped.length ? `Skipped: ${d.skipped.join(", ")}` : ""}</span>
            <a className="btn-link" href={api.screenExportUrl(jobId)} download>
              Download CSV
            </a>
          </div>
        </>
      )}
    </div>
  );
}

/** A GENE_<symbol> target has no QSAR model, so "Run screen" degrades to a
    plain docking run — reuses the Docking tab's own result shape/rendering
    rather than a hardcoded id, matching the original app's routing. */
function GeneOnlyDockResults({
  results,
  receptorPdbPath,
  targetId,
  advanced,
  caveat,
}: {
  results: DockResultRow[];
  receptorPdbPath: string | null;
  targetId: string;
  advanced: AdvancedDockingBody | null;
  caveat: string | null;
}) {
  const [openRows, setOpenRows] = useState<Set<number>>(new Set());
  const toggle = (i: number) =>
    setOpenRows((s) => {
      const n = new Set(s);
      n.has(i) ? n.delete(i) : n.add(i);
      return n;
    });
  return (
    <div>
      {caveat && <Notice>{caveat}</Notice>}
      <div className="max-h-[calc(100vh-260px)] overflow-auto">
        <table className="w-full border-collapse text-[13px]">
          <thead>
            <tr>
              {["", "Compound", "Confidence", "Vina affinity (kcal/mol)", "Status", "Fresh decoy check"].map((h) => (
                <th key={h} className="sticky top-0 z-10 border-b border-line bg-surface2 px-3 py-2.5 text-left text-[10.5px] font-semibold uppercase tracking-wide text-inkmut">
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {results.map((r, i) => {
              const hasDetail = !!r.interaction_png || r.status === "ok";
              const open = openRows.has(i);
              return (
                <Fragment key={i}>
                  <tr className={hasDetail ? "cursor-pointer hover:bg-canvas" : ""} onClick={() => hasDetail && toggle(i)}>
                    <td className="border-b border-surface2 px-3 py-2.5 text-brand-600">{hasDetail ? (open ? "▾" : "▸") : ""}</td>
                    <td className="smi-mono border-b border-surface2 px-3 py-2.5">{r.smiles}</td>
                    <td className="border-b border-surface2 px-3 py-2.5">
                      <span className="chip">
                        <ConfidenceDot level={r.confidence} />
                        {r.confidence || "—"}
                      </span>
                    </td>
                    <td className="border-b border-surface2 px-3 py-2.5">{r.vina_score ?? "—"}</td>
                    <td className="border-b border-surface2 px-3 py-2.5 text-inkmut">{r.status === "ok" ? `${r.n_valid} valid pose(s)` : r.reason || r.status}</td>
                    <td className="border-b border-surface2 px-3 py-2.5">
                      {r.status === "ok" ? <FreshDecoyButton smiles={r.smiles} targetId={targetId} advanced={advanced} /> : <span className="text-inkmut">—</span>}
                    </td>
                  </tr>
                  {hasDetail && open && (
                    <tr>
                      <td className="border-b border-surface2" />
                      <td colSpan={20} className="border-b border-surface2 p-0">
                        <div className="bg-surface2/40 px-5 py-3.5">
                          {r.interaction_png ? (
                            <img src={`data:image/png;base64,${r.interaction_png}`} className="max-w-full rounded-lg border border-line bg-white" />
                          ) : (
                            <div className="text-[13px] text-inkmut">No interaction diagram for this pose.</div>
                          )}
                          {r.pose_pdb && (
                            <div className="mt-2">
                              <DownloadComplexButton smiles={r.smiles} posePdb={r.pose_pdb} receptorPdbPath={receptorPdbPath} />
                            </div>
                          )}
                        </div>
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
