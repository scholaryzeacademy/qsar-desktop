import { useState } from "react";
import * as api from "../lib/api";
import { apiUrl } from "../lib/api";
import { combinePdbText, fetchTextCached } from "../lib/mol3d";
import type { AdvancedDockingBody, DockResultRow } from "../lib/types";
import { PoseViewer } from "./PoseViewer";

/** Downloads the receptor+pose "complex" PDB for one docked compound —
    the same two structures PoseViewer already renders together in 3D,
    just written out as a real file. receptorPdbPath is the file that was
    ACTUALLY docked against for this job (from the job's own response),
    not necessarily whatever the target's current default happens to be
    now. */
export function DownloadComplexButton({
  smiles,
  posePdb,
  receptorPdbPath,
}: {
  smiles: string;
  posePdb?: string | null;
  receptorPdbPath?: string | null;
}) {
  const [busy, setBusy] = useState(false);
  if (!posePdb) return null;

  const run = async () => {
    setBusy(true);
    try {
      const receptorPdb = receptorPdbPath
        ? await fetchTextCached(apiUrl(`/api/docking/receptor_file?path=${encodeURIComponent(receptorPdbPath)}`))
        : null;
      const text = receptorPdb ? combinePdbText(receptorPdb, posePdb) : posePdb;
      const blob = new Blob([text], { type: "chemical/x-pdb" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      const safeName = smiles.replace(/[^A-Za-z0-9]+/g, "_").slice(0, 40) || "compound";
      a.href = url;
      a.download = `${safeName}${receptorPdb ? "_complex" : "_pose"}.pdb`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } finally {
      setBusy(false);
    }
  };

  return (
    <button type="button" className="btn-link" disabled={busy} onClick={run}>
      {busy ? "Preparing…" : receptorPdbPath ? "Download complex (PDB)" : "Download pose (PDB)"}
    </button>
  );
}

export function EnrichmentChip({ r }: { r: Pick<DockResultRow, "enrichment_percentile" | "enrichment_context"> }) {
  const pct = r.enrichment_percentile;
  if (pct == null) return <span className="text-inkmut">—</span>;
  const ec = r.enrichment_context || {};
  const dcls = pct >= 90 ? "bg-brand-500" : pct >= 65 ? "bg-amber" : "bg-clay";
  return (
    <span
      className="chip min-w-0 max-w-full"
      title={`${pct}th pct${ec.beats_best_known_active ? " · beats best known active" : ""} — ${ec.n_active ?? "?"} known active(s), ${ec.n_decoy ?? "?"} decoys (${ec.decoy_method ?? "?"})`}
    >
      <span className={`dot shrink-0 ${dcls}`} />
      <span className="min-w-0 truncate">
        {pct}th pct{ec.beats_best_known_active ? " · beats best" : ""}
      </span>
    </span>
  );
}

export function InteractionTable({ interactions }: { interactions?: DockResultRow["interactions"] }) {
  if (!interactions || !interactions.length) return null;
  const rows = [...interactions].sort((a, b) => (a.distance ?? 0) - (b.distance ?? 0));
  return (
    <div className="mt-2.5">
      <div className="px-0 pb-1 text-[10.5px] font-bold uppercase tracking-wider text-brand-700">
        Protein-ligand nonbonding interactions ({rows.length})
      </div>
      <table className="w-full border-collapse text-[13px]">
        <thead>
          <tr>
            {["Name", "Category", "Type", "Distance (Å)"].map((h) => (
              <th key={h} className="border-b border-line px-3 py-2 text-left text-[10.5px] font-semibold uppercase tracking-wide text-inkmut">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i}>
              <td className="border-b border-surface2 px-3 py-2">{r.name || r.residue}</td>
              <td className="border-b border-surface2 px-3 py-2">{r.category || ""}</td>
              <td className="border-b border-surface2 px-3 py-2">{r.label || r.type || ""}</td>
              <td className="border-b border-surface2 px-3 py-2">{r.distance ?? "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function FreshDecoyButton({ smiles, targetId, advanced }: { smiles: string; targetId: string | null; advanced: AdvancedDockingBody | null }) {
  const [busy, setBusy] = useState(false);
  const [label, setLabel] = useState("Run Fresh Decoy Validation");
  const [status, setStatus] = useState<{ kind: "muted" | "ok" | "err"; text: string } | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);

  const run = async () => {
    if (!targetId) {
      setStatus({ kind: "err", text: "No target context for this result." });
      return;
    }
    setBusy(true);
    setLabel("Generating decoys & docking (~2-5 min)…");
    setStatus({ kind: "muted", text: "Generating ~50 decoys matched to this compound…" });
    try {
      const sub = await api.submitFreshDecoy(targetId, smiles, advanced);
      setJobId(sub.job_id);
      let j;
      while (true) {
        await api.sleep(2000);
        j = await api.pollRetry(() => api.freshDecoyJob(sub.job_id));
        if (j.status === "done" || j.status === "error" || j.status === "cancelled") break;
        const done = j.done || 0;
        const total = j.total || "?";
        setStatus({ kind: "muted", text: `Docking ${done}/${total}…` });
        setLabel(`Docking ${done}/${total}…`);
      }
      if (j.status === "cancelled") {
        setStatus({ kind: "muted", text: "Stopped by user." });
        return;
      }
      if (j.status === "error") {
        setStatus({ kind: "err", text: j.error || "failed" });
        return;
      }
      const res = j.result!;
      if (res.error) {
        setStatus({ kind: "muted", text: res.error });
        return;
      }
      setStatus({
        kind: "ok",
        text: `Fresh percentile: ${res.percentile}% · Decoy discrimination: ${res.discrimination} — compound score ${res.compound_score} kcal/mol vs ${res.n_decoys_docked} freshly-docked, property-matched & topologically-dissimilar decoys${res.n_decoys_failed ? ` (${res.n_decoys_failed} failed to dock)` : ""}.`,
      });
    } catch (e: any) {
      setStatus({ kind: "err", text: e.message || "Error" });
    } finally {
      setBusy(false);
      setJobId(null);
      setLabel("Run Fresh Decoy Validation");
    }
  };

  const stop = async () => {
    if (!jobId) return;
    try {
      await api.cancelFreshDecoy(jobId);
    } catch {
      /* the poll loop will still surface a final status either way */
    }
  };

  return (
    <div onClick={(e) => e.stopPropagation()}>
      <button type="button" className="btn-link" disabled={busy} onClick={run}>
        {label}
      </button>
      {busy && jobId && (
        <button type="button" className="btn-link ml-1.5" onClick={stop}>
          Stop
        </button>
      )}
      {status && (
        <div
          className={`mt-1.5 max-w-[220px] text-[12px] ${
            status.kind === "ok" ? "font-medium text-brand-700" : status.kind === "err" ? "text-clay" : "text-inkmut"
          }`}
        >
          {status.text}
        </div>
      )}
    </div>
  );
}

export function DockDetailPanel({ r, receptorPdbPath }: { r: DockResultRow; receptorPdbPath?: string | null }) {
  const canView = !!r.interaction_png;
  return (
    <div className="bg-surface2/40 px-5 py-3.5">
      {canView && r.residue_overlap_pct != null && (
        <div className="mb-2 text-[12.5px] text-inkmut">Shares {r.residue_overlap_pct}% of the reference drug's contact residues.</div>
      )}
      {canView && r.interaction_source && <div className="mb-2 text-[12.5px] text-inkmut">Interaction detection: {r.interaction_source}.</div>}
      {canView ? (
        <img src={`data:image/png;base64,${r.interaction_png}`} className="max-w-full rounded-lg border border-line bg-white" />
      ) : (
        <div className="py-2 text-[13px] text-inkmut">No interaction diagram for this pose.</div>
      )}
      <InteractionTable interactions={r.interactions} />
      {r.pose_pdb && <PoseViewer posePdb={r.pose_pdb} receptorPdbPath={receptorPdbPath} interactions={r.interactions} />}
      {r.pose_pdb && (
        <div className="mt-2">
          <DownloadComplexButton smiles={r.smiles} posePdb={r.pose_pdb} receptorPdbPath={receptorPdbPath} />
        </div>
      )}
    </div>
  );
}
