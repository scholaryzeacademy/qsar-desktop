import { useState } from "react";
import * as api from "../lib/api";
import type { RecommendationResponse } from "../lib/types";

export function WhyThisButton({ targetId }: { targetId: string }) {
  const [rec, setRec] = useState<RecommendationResponse | "loading" | "none" | null>(null);

  const show = async () => {
    setRec("loading");
    try {
      setRec(await api.targetRecommendation(targetId));
    } catch {
      setRec("none");
    }
  };

  return (
    <div>
      <button type="button" className="btn-link mt-2" onClick={show}>
        Why this?
      </button>
      {rec === "loading" && <div className="field-hint">Loading…</div>}
      {rec === "none" && <div className="field-hint">No structural-evidence data for this target.</div>}
      {rec && typeof rec === "object" && <RecommendationCard rec={rec} />}
    </div>
  );
}

export function RecommendationCard({ rec }: { rec: RecommendationResponse }) {
  const v = rec.our_validation;
  const p = rec.panel_evidence;
  return (
    <div className={`mt-2 rounded-xl border px-3 py-2.5 ${v.validated ? "border-brand-300/50 bg-brand-500/[0.06]" : "border-amber/30 bg-amber/[0.06]"}`}>
      <div className="mb-1 flex items-center gap-2">
        <span className={`badge ${v.validated ? "bg-brand-500/15 text-brand-800" : "bg-amber/15 text-amber"}`}>
          {v.validated ? "✓ VALIDATED" : "UNVALIDATED"}
        </span>
      </div>
      <div className="mb-1 text-[13px]">{rec.headline}</div>
      <div className="text-[12.5px] text-ink/80">
        {v.reference_rmsd != null ? <b>{v.reference_rmsd} Å</b> : <span className="text-inkmut">no redocking</span>} redocking &nbsp;·&nbsp;{" "}
        {v.enrichment_auc != null ? <b>AUC {v.enrichment_auc}</b> : <span className="text-inkmut">no enrichment test</span>} enrichment
        {v.pdb_id ? (
          <>
            {" "}
            &nbsp;·&nbsp; PDB {v.pdb_id}/{v.ligand_resname || ""}
          </>
        ) : null}
      </div>
      <h5 className="mb-1 mt-2.5 text-[11px] font-bold uppercase tracking-wide text-brand-700">Structural evidence (panel_results_v2.csv)</h5>
      <div className="text-[12.5px] text-ink/80">
        Top-ranked: <b>{p.top_ranked_pdb_id || "—"}{p.top_ranked_chain ? ":" + p.top_ranked_chain : ""}</b> ({p.top_ranked_ligand || "?"})
        <br />
        Resolution {p.resolution ?? "—"} Å ({p.resolution_tier || "?"}) · RSCC {p.ligand_RSCC ?? "—"} · RSR {p.ligand_RSR ?? "—"} · R-free {p.r_free ?? "—"}
        <br />
        {p.n_qualifying_structures ?? "?"} qualifying structures · {p.chembl_activity_records ?? "?"} ChEMBL activity records
      </div>
      {p.note && <div className="mt-1.5 text-[11px] text-inkmut">{p.note}</div>}
    </div>
  );
}
