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

const DISEASE_PAGE = 50;
const TARGET_PAGE = 30;

/** Disease-first target browser, shared by Screen and Docking:
      1. an optional, searchable disease combobox — opens on focus with a
         browsable (capped) list, narrows as you type
      2. a target search box + result list — opens on focus (showing
         already-downloaded targets, or a disease's ranked targets once
         one is picked), narrows/expands as you type
      3. once a target is picked, its structure loads and previews
         automatically (no extra "View binding site in 3D" click needed
         for the default view — that modal still exists for deeper
         pocket-residue editing, this is just "here's what got picked")

    Both dropdowns render in normal document flow (not position:absolute)
    deliberately — this component sits inside a sidebar with its own
    independent scroll (see ScreenTab/DockingTab's <aside overflow-y-auto>),
    and an absolutely-positioned panel gets silently clipped by that
    ancestor depending on scroll position. Pushing the layout down while
    open is a small, well-understood tradeoff for a panel that reliably
    shows up every time.

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
  const [targetOpen, setTargetOpen] = useState(false);
  const [ranked, setRanked] = useState<DiseaseTarget[] | null>(null);
  const [rankedLoading, setRankedLoading] = useState(false);
  const diseaseBoxRef = useRef<HTMLDivElement>(null);
  const targetBoxRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!diseaseId) {
      setRanked(null);
      setRankedLoading(false);
      return;
    }
    let cancelled = false;
    setRankedLoading(true);
    api
      .targetsForDisease(diseaseId)
      .then((d) => !cancelled && setRanked(d.targets))
      .catch(() => !cancelled && setRanked([]))
      .finally(() => !cancelled && setRankedLoading(false));
    return () => {
      cancelled = true;
    };
  }, [diseaseId]);

  // A target picked outside this component (e.g. this tab remembers the
  // last-used target, or a sibling control changed it) needs its label
  // reflected in the search box too — otherwise the box shows blank even
  // though something real is selected. Only fires when the box doesn't
  // already have text, so it never clobbers what the user is typing.
  useEffect(() => {
    if (!targetId || targetQuery) return;
    const installed = targets.find((t) => t.target_id === targetId);
    setTargetQuery(installed ? installed.target_id : targetId.startsWith("GENE_") ? targetId.slice(5) : targetId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [targetId]);

  useEffect(() => {
    const onDocClick = (e: MouseEvent) => {
      if (diseaseBoxRef.current && !diseaseBoxRef.current.contains(e.target as Node)) setDiseaseOpen(false);
      if (targetBoxRef.current && !targetBoxRef.current.contains(e.target as Node)) setTargetOpen(false);
    };
    document.addEventListener("mousedown", onDocClick);
    return () => document.removeEventListener("mousedown", onDocClick);
  }, []);

  const diseaseMatches = useMemo(() => {
    const q = diseaseQuery.trim().toLowerCase();
    const pool = q ? diseases.filter((d) => d.name.toLowerCase().includes(q)) : diseases;
    return pool.slice(0, DISEASE_PAGE);
  }, [diseases, diseaseQuery]);
  const diseaseTruncated = diseaseMatches.length === DISEASE_PAGE && diseases.length > DISEASE_PAGE;

  const selectDisease = (d: { disease_id: string; name: string }) => {
    setDiseaseId(d.disease_id);
    setDiseaseQuery(d.name);
    setDiseaseOpen(false);
    setTargetQuery("");
    setTargetOpen(true); // jump straight to this disease's ranked targets, no extra click
  };

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
    const detailsById = new Map((dockingStatus?.target_details || []).map((d: any) => [d.target_id, d]));
    const installed: Row[] = targets
      .filter((t) => !q || t.target_id.toLowerCase().includes(q))
      .map((t) => {
        const det = detailsById.get(t.target_id) as any;
        const marker: Row["marker"] = det ? (det.validated ? "validated" : "unvalidated") : "validated";
        return {
          value: t.target_id,
          label: t.target_id,
          marker,
          sub: `${t.n_compounds ?? "?"} compounds · test R² ${t.test_r2 ?? "—"}`,
        };
      });
    // The registry's full ~600 targets (downloadable + docking-only) stay
    // hidden until the user actually types — only `installed` (bounded to
    // whatever's already downloaded, typically a handful) is safe to show
    // just from focusing the box.
    if (!q) return installed.slice(0, TARGET_PAGE);
    const installedIds = new Set(installed.map((r) => r.value));
    const downloadable: Row[] = gateApi.downloadableExtraIds
      .filter((id) => !installedIds.has(id) && id.toLowerCase().includes(q))
      .map((id) => ({ value: id, label: id, marker: "not-downloaded" as const, sub: "not downloaded yet" }));
    const coveredIds = new Set([...installedIds, ...downloadable.map((r) => r.value)]);
    // Every OTHER registry target (almost entirely docking-only, no QSAR
    // model — the ones a disease-independent search used to miss
    // entirely) — matched by symbol (GENE_<symbol>) or raw id.
    const dockingOnly: Row[] = (dockingStatus?.target_details || [])
      .filter((d: any) => {
        if (coveredIds.has(d.target_id)) return false;
        const symbol = d.target_id.startsWith("GENE_") ? d.target_id.slice(5) : d.target_id;
        return d.target_id.toLowerCase().includes(q) || symbol.toLowerCase().includes(q);
      })
      .map((d: any) => ({
        value: d.target_id,
        label: d.target_id.startsWith("GENE_") ? d.target_id.slice(5) : d.target_id,
        marker: "docking-only" as const,
        sub: `docking only, no QSAR model · ${d.validated ? "✓ structure validated" : "⚠ structure not yet validated"}`,
      }));
    return [...installed, ...downloadable, ...dockingOnly].slice(0, TARGET_PAGE);
  }, [diseaseId, ranked, targetQuery, targets, gateApi.downloadableExtraIds, dockingStatus]);

  const selectTarget = (r: Row) => {
    gateApi.select(r.value);
    setTargetQuery(r.label);
    setTargetOpen(false);
  };

  const selectedRow = rows.find((r) => r.value === targetId);
  const dockDetail = dockingStatus?.target_details?.find((d: any) => d.target_id === targetId) ?? null;
  const geneOnly = targetId.startsWith("GENE_");

  return (
    <div>
      <label className="field-label">Disease (optional)</label>
      <div ref={diseaseBoxRef}>
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
        {diseaseOpen && (
          <div className="mt-1.5 max-h-[240px] overflow-y-auto rounded-lg border border-line bg-surface">
            {!diseaseMatches.length && <div className="p-2.5 text-[12.5px] text-inkmut">No matching diseases.</div>}
            {diseaseMatches.map((d) => (
              <div
                key={d.disease_id}
                className="cursor-pointer border-b border-line/70 px-2.5 py-1.5 text-[12.5px] last:border-0 hover:bg-surface2/60"
                onClick={() => selectDisease(d)}
              >
                {d.name}
                {d.is_therapeutic_area ? <span className="ml-1.5 text-inkmut">(therapeutic area)</span> : null}
              </div>
            ))}
            {diseaseTruncated && (
              <div className="border-t border-line px-2.5 py-1.5 text-[11px] text-inkmut">
                Showing the first {DISEASE_PAGE} — keep typing to narrow.
              </div>
            )}
          </div>
        )}
      </div>

      <label className="field-label" style={{ marginTop: 12 }}>
        Target
      </label>
      <div ref={targetBoxRef}>
        <input
          className="field-input"
          placeholder={diseaseId ? "Filter this disease's targets…" : "Search targets by id…"}
          value={targetQuery}
          onFocus={() => setTargetOpen(true)}
          onChange={(e) => {
            setTargetQuery(e.target.value);
            setTargetOpen(true);
          }}
        />
        {!diseaseId && !targetQuery.trim() && !targetOpen && !targets.length && (
          <div className="field-hint">Pick a disease above, or type a target id to search.</div>
        )}
        {targetOpen && (
          <div className="mt-1.5 max-h-[280px] overflow-y-auto rounded-lg border border-line bg-surface">
            {!rows.length && (
              <div className="p-2.5 text-[12.5px] text-inkmut">
                {diseaseId && rankedLoading
                  ? "Loading targets for this disease…"
                  : diseaseId || targetQuery.trim()
                  ? "No matching targets."
                  : "No targets downloaded yet — type an id to search all targets."}
              </div>
            )}
            {rows.map((r) => {
              const on = r.value === targetId || r.value === gateApi.pendingId;
              return (
                <div
                  key={r.value}
                  onClick={() => selectTarget(r)}
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
      </div>
      <DownloadGateBar gate={gateApi.gate} onRetry={gateApi.retry} onStop={gateApi.stop} />

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
