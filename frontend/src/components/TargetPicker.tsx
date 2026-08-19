import { useEffect, useState } from "react";
import { useAppData } from "../lib/AppDataContext";
import * as api from "../lib/api";
import type { DiseaseTarget } from "../lib/types";

interface Option {
  value: string;
  label: string;
}

/** Disease filter + target select, shared by Screen and Docking — mirrors
    populateGroupTargets()/populateScreenTargets()/populateDockTargets() from
    the original app: picking a disease re-ranks the target list and may
    introduce synthetic GENE_<symbol> ids for proteins with disease evidence
    but no trained QSAR model (docking-only). */
export function TargetPicker({ targetId, onChange }: { targetId: string; onChange: (id: string) => void }) {
  const { targets, diseases } = useAppData();
  const [diseaseId, setDiseaseId] = useState("");
  const [ranked, setRanked] = useState<DiseaseTarget[] | null>(null);

  useEffect(() => {
    let cancelled = false;
    if (!diseaseId) {
      setRanked(null);
      return;
    }
    api
      .targetsForDisease(diseaseId)
      .then((d) => !cancelled && setRanked(d.targets))
      .catch(() => !cancelled && setRanked([]));
    return () => {
      cancelled = true;
    };
  }, [diseaseId]);

  const options: Option[] = ranked
    ? ranked.map((t) =>
        t.has_qsar_model
          ? { value: t.target_id!, label: `${t.validated ? "✓" : "⚠"} ${t.target_symbol} (${t.target_id}) — score ${t.disease_score}` }
          : { value: "GENE_" + t.target_symbol, label: `⚙ ${t.target_symbol} — score ${t.disease_score} (no QSAR model — docking only)` }
      )
    : targets.map((t) => ({ value: t.target_id, label: t.target_id }));

  const optionKey = options.map((o) => o.value).join("|");
  useEffect(() => {
    if (!options.length) {
      if (targetId) onChange("");
      return;
    }
    if (!options.find((o) => o.value === targetId)) onChange(options[0].value);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [optionKey]);

  const current = targets.find((t) => t.target_id === targetId);
  const geneOnly = targetId.startsWith("GENE_");

  return (
    <div>
      {diseases.length > 0 && (
        <>
          <label className="field-label">Disease (optional, ranks &amp; filters targets)</label>
          <select className="field-input" value={diseaseId} onChange={(e) => setDiseaseId(e.target.value)}>
            <option value="">— all targets —</option>
            {diseases.map((d) => (
              <option key={d.disease_id} value={d.disease_id}>
                {d.name}
                {d.is_therapeutic_area ? " (therapeutic area)" : ""}
              </option>
            ))}
          </select>
        </>
      )}
      <label className="field-label" style={{ marginTop: 12 }}>
        Target
      </label>
      <select className="field-input" value={targetId} onChange={(e) => onChange(e.target.value)}>
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
      <div className="field-hint">
        {geneOnly ? (
          <span className="text-inkmut">No QSAR model for this protein — structure-based docking only.</span>
        ) : current ? (
          <>
            {current.n_compounds ?? "?"} compounds · test R² {current.test_r2 ?? "—"} · RMSE {current.test_rmse ?? "—"}
          </>
        ) : null}
      </div>
    </div>
  );
}

export function PlainTargetSelect({ targetId, onChange }: { targetId: string; onChange: (id: string) => void }) {
  const { targets } = useAppData();
  useEffect(() => {
    if (!targetId && targets.length) onChange(targets[0].target_id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [targets.length]);
  const current = targets.find((t) => t.target_id === targetId);
  return (
    <div>
      <label className="field-label">Target</label>
      <select className="field-input" value={targetId} onChange={(e) => onChange(e.target.value)}>
        {targets.map((t) => (
          <option key={t.target_id} value={t.target_id}>
            {t.target_id}
          </option>
        ))}
      </select>
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
