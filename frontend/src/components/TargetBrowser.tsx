import { useEffect, useMemo, useRef, useState } from "react";
import { useAppData } from "../lib/AppDataContext";
import * as api from "../lib/api";
import { useDownloadGate, type Kind } from "../lib/useDownloadGate";
import { DownloadGateBar } from "./DownloadGateBar";
import { ReceptorPreview } from "./ReceptorPreview";
import type { AdvancedDockingState } from "../lib/useAdvancedDocking";
import type { DiseaseTarget } from "../lib/types";

interface Row {
  value: string; // real target_id, or "GENE_<symbol>" for docking-only
  label: string;
  marker: "validated" | "unvalidated" | "docking-only" | "not-downloaded";
  sub: string;
}

const MARKER_ICON: Record<Row["marker"], string> = {
  validated: "✓",
  unvalidated: "⚠",
  "docking-only": "⚙",
  "not-downloaded": "⬇",
};
const MARKER_CLS: Record<Row["marker"], string> = {
  validated: "text-brand-600",
  unvalidated: "text-amber",
  "docking-only": "text-inkmut",
  "not-downloaded": "text-brand-600",
};

/** Disease-first target browser, shared by Screen and Docking:
      1. an optional, searchable disease combobox
      2. a target search box + result list (never a giant always-expanded
         list of every target — nothing renders until you either pick a
         disease or type a query)
      3. once a target is picked, its structure loads and previews
         automatically (no extra "View binding site in 3D" click needed
         for the default view — that modal still exists for deeper
         pocket-residue editing, this is just "here's what got picked")

    Replaces the old TargetPicker component's UI; the manifest-aware
    auto-download gating (useDownloadGate) is unchanged, just re-skinned
    into a real list instead of a plain <select>. */
export function TargetBrowser({
  targetId,
  onChange,
  need = ["model"],
  adv,
}: {
  targetId: string;
  onChange: (id: string) => void;
  need?: Kind[];
  /** From the owning tab's useAdvancedDocking(targetId) — reused here so
      the structure preview doesn't duplicate that hook's own site/
      candidates fetch for the same target. */
  adv: AdvancedDockingState;
}) {
  const { targets, diseases, dockingStatus } = useAppData();
  const gateApi = useDownloadGate(need, onChange);

  const [diseaseQuery, setDiseaseQuery] = useState("");
  const [diseaseId, setDiseaseId] = useState("");
  const [diseaseOpen, setDiseaseOpen] = useState(false);
  const [targetQuery, setTargetQuery] = useState("");
  const [ranked, setRanked] = useState<DiseaseTarget[] | null>(null);
  const diseaseBoxRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!diseaseId) {
      setRanked(null);
      return;
    }
    let cancelled = false;
    api
      .targetsForDisease(diseaseId)
      .then((d) => !cancelled && setRanked(d.targets))
      .catch(() => !cancelled && setRanked([]));
    return () => {
      cancelled = true;
    };
  }, [diseaseId]);

  useEffect(() => {
    const onDocClick = (e: MouseEvent) => {
      if (diseaseBoxRef.current && !diseaseBoxRef.current.contains(e.target as Node)) setDiseaseOpen(false);
    };
    document.addEventListener("mousedown", onDocClick);
    return () => document.removeEventListener("mousedown", onDocClick);
  }, []);

  const diseaseMatches = useMemo(() => {
    const q = diseaseQuery.trim().toLowerCase();
    const pool = q ? diseases.filter((d) => d.name.toLowerCase().includes(q)) : diseases;
    return pool.slice(0, 12);
  }, [diseases, diseaseQuery]);

  const clearDisease = () => {
    setDiseaseId("");
    setDiseaseQuery("");
    setRanked(null);
  };

  const rows: Row[] = useMemo(() => {
    const q = targetQuery.trim().toLowerCase();
    if (diseaseId) {
      return (ranked || [])
        .filter((t) => !q || t.target_symbol.toLowerCase().includes(q) || (t.target_id || "").toLowerCase().includes(q))
        .map((t) => {
          const value = t.has_qsar_model ? t.target_id! : "GENE_" + t.target_symbol;
          const marker: Row["marker"] = !t.has_qsar_model ? "docking-only" : t.validated ? "validated" : "unvalidated";
          const label = t.has_qsar_model ? `${t.target_symbol} (${t.target_id})` : t.target_symbol;
          return { value, label, marker, sub: `score ${t.disease_score}${t.has_qsar_model ? "" : " · docking only, no QSAR model"}` };
        });
    }
    if (!q) return [];
    const installed: Row[] = targets
      .filter((t) => t.target_id.toLowerCase().includes(q))
      .map((t) => ({
        value: t.target_id,
        label: t.target_id,
        marker: "validated",
        sub: `${t.n_compounds ?? "?"} compounds · test R² ${t.test_r2 ?? "—"}`,
      }));
    const installedIds = new Set(installed.map((r) => r.value));
    const downloadable: Row[] = gateApi.downloadableExtraIds
      .filter((id) => !installedIds.has(id) && id.toLowerCase().includes(q))
      .map((id) => ({ value: id, label: id, marker: "not-downloaded", sub: "not downloaded yet" }));
    return [...installed, ...downloadable].slice(0, 25);
  }, [diseaseId, ranked, targetQuery, targets, gateApi.downloadableExtraIds]);

  const selectedRow = rows.find((r) => r.value === targetId);
  const dockDetail = dockingStatus?.target_details?.find((d: any) => d.target_id === targetId) ?? null;
  const geneOnly = targetId.startsWith("GENE_");

  return (
    <div>
      <label className="field-label">Disease (optional)</label>
      <div className="relative" ref={diseaseBoxRef}>
        <div className="flex gap-1.5">
          <input
            className="field-input"
            placeholder="Search diseases…"
            value={diseaseQuery}
            onFocus={() => setDiseaseOpen(true)}
            onChange={(e) => {
              // Typing again after a disease is already picked starts a
              // new search — drop the stale selection/ranked list, but
              // keep what was just typed (don't let clearDisease()'s own
              // diseaseQuery reset clobber it).
              if (diseaseId) {
                setDiseaseId("");
                setRanked(null);
              }
              setDiseaseQuery(e.target.value);
              setDiseaseOpen(true);
            }}
          />
          {diseaseId && (
            <button type="button" className="btn-link px-2.5" onClick={clearDisease} title="Clear disease filter">
              ✕
            </button>
          )}
        </div>
        {diseaseOpen && diseaseMatches.length > 0 && (
          <div className="absolute z-20 mt-1 max-h-[220px] w-full overflow-y-auto rounded-lg border border-line bg-surface shadow-card">
            {diseaseMatches.map((d) => (
              <div
                key={d.disease_id}
                className="cursor-pointer border-b border-line/70 px-2.5 py-1.5 text-[12.5px] last:border-0 hover:bg-surface2/60"
                onClick={() => {
                  setDiseaseId(d.disease_id);
                  setDiseaseQuery(d.name);
                  setDiseaseOpen(false);
                }}
              >
                {d.name}
                {d.is_therapeutic_area ? <span className="ml-1.5 text-inkmut">(therapeutic area)</span> : null}
              </div>
            ))}
          </div>
        )}
      </div>

      <label className="field-label" style={{ marginTop: 12 }}>
        Target
      </label>
      <input
        className="field-input"
        placeholder={diseaseId ? "Filter this disease's targets…" : "Search targets by id…"}
        value={targetQuery}
        onChange={(e) => setTargetQuery(e.target.value)}
      />
      {!diseaseId && !targetQuery.trim() && (
        <div className="field-hint">Pick a disease above, or type a target id to search.</div>
      )}
      {(diseaseId || targetQuery.trim()) && (
        <div className="mt-1.5 max-h-[260px] overflow-y-auto rounded-lg border border-line">
          {!rows.length && <div className="p-2 text-[12.5px] text-inkmut">No matching targets.</div>}
          {rows.map((r) => {
            const on = r.value === targetId || r.value === gateApi.pendingId;
            return (
              <div
                key={r.value}
                onClick={() => gateApi.select(r.value)}
                className={`flex cursor-pointer items-center gap-2 border-b border-line/70 px-2.5 py-1.5 text-[12.5px] last:border-0 hover:bg-surface2/60 ${on ? "bg-brand-500/[0.08]" : ""}`}
              >
                <span className={`w-4 text-center font-bold ${MARKER_CLS[r.marker]}`}>{MARKER_ICON[r.marker]}</span>
                <span className="flex-1">
                  <span className="font-semibold text-ink">{r.label}</span>
                  <span className="ml-1.5 text-inkmut">{r.sub}</span>
                </span>
              </div>
            );
          })}
        </div>
      )}
      <DownloadGateBar gate={gateApi.gate} onRetry={gateApi.retry} />

      {targetId && !gateApi.gate.active && (
        <div className="mt-3">
          {geneOnly ? (
            <div className="field-hint text-inkmut">No QSAR model for this protein — structure-based docking only.</div>
          ) : selectedRow ? (
            <div className="field-hint">{selectedRow.sub}</div>
          ) : null}
          {adv.site?.receptorUrl && (
            <div className="mt-2">
              <div className="field-hint mb-1">
                {(() => {
                  const def = adv.candidates?.find((c) => c.is_current_default);
                  if (!def) return "Structure preview";
                  const status =
                    dockDetail?.validated === true ? "✓ validated" : dockDetail?.validated === false ? "⚠ not yet validated" : "";
                  return `${def.pdb_id} (automatic default)${status ? ` — ${status}` : ""}`;
                })()}
              </div>
              <ReceptorPreview receptorUrl={adv.site.receptorUrl} ligandUrl={adv.site.ligandUrl} />
            </div>
          )}
        </div>
      )}
    </div>
  );
}
