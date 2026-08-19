interface Detail {
  name?: string;
  target_id?: string;
  validated: boolean;
  reference_rmsd?: number | null;
  enrichment_auc?: number | null;
  enrichment_ef20?: number | null;
  enrichment_n?: number | null;
}

export function ValidationPanel({ details }: { details: Detail[] }) {
  if (!details.length) return null;
  return (
    <div className="my-1.5">
      <h5 className="mb-1.5 text-[11px] font-bold uppercase tracking-wide text-brand-700">Per-target validation</h5>
      {details.map((d, i) => {
        const rmsd = d.reference_rmsd != null ? <><b>{d.reference_rmsd} Å</b> redocking</> : <span className="text-inkmut">no redocking</span>;
        const enr =
          d.enrichment_auc != null ? (
            <>
              <b>AUC {d.enrichment_auc}</b> enrichment{d.enrichment_ef20 != null ? ` (EF@20% ${d.enrichment_ef20}${d.enrichment_n ? `, n=${d.enrichment_n}` : ""})` : ""}
            </>
          ) : (
            <span className="text-inkmut">no enrichment test</span>
          );
        return (
          <div key={i} className={`mb-2 rounded-xl border px-3 py-2.5 ${d.validated ? "border-brand-300/50 bg-brand-500/[0.06]" : "border-amber/30 bg-amber/[0.06]"}`}>
            <div className="mb-1 flex items-center gap-2.5">
              <b className="text-[13px]">{d.name || d.target_id}</b>
              <span className={`badge ${d.validated ? "bg-brand-500/15 text-brand-800" : "bg-amber/15 text-amber"}`}>
                {d.validated ? "✓ VALIDATED" : "UNVALIDATED"}
              </span>
            </div>
            <div className="text-[12.5px] text-ink/80">
              {rmsd} &nbsp;·&nbsp; {enr}
            </div>
          </div>
        );
      })}
      <div className="text-[11.5px] text-inkmut">
        Redocking &lt; 2 Å confirms the pose geometry; enrichment AUC measures separation of known actives from decoys. Trust scores only for validated targets.
      </div>
    </div>
  );
}
