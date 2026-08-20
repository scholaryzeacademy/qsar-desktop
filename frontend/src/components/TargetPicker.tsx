import { useEffect, useMemo, useState } from "react";
import { useAppData } from "../lib/AppDataContext";
import * as api from "../lib/api";
import { fmtBytes } from "../lib/format";
import type { DiseaseTarget, DownloadsStatus } from "../lib/types";

type Kind = "model" | "docking";

interface Option {
  value: string;
  label: string;
}

interface GateState {
  active: boolean;
  kind: Kind | null;
  done: number;
  total: number;
  error: string | null;
}

const IDLE_GATE: GateState = { active: false, kind: null, done: 0, total: 0, error: null };

/** Shared by TargetPicker and PlainTargetSelect: makes the picker
    manifest-aware (the option list can include real targets that aren't
    downloaded yet, see backend/downloads.py) and gates a selection
    behind an inline auto-download — the caller's onChange only ever
    fires once the target's data for `need` actually exists on disk, so
    every consuming tab keeps working exactly as it does today with zero
    changes of its own.

    Falls back to pure pass-through (today's exact behavior) if the
    downloads manifest is unavailable (DOWNLOAD_BASE_URL unset, or the
    split web deployment) — `manifestEnabled` stays false and nothing
    below ever triggers. */
function useDownloadGate(need: Kind[], onReady: (id: string) => void) {
  const { targets, refresh } = useAppData();
  const [manifest, setManifest] = useState<DownloadsStatus | null>(null);
  const [manifestEnabled, setManifestEnabled] = useState(true);
  const [gate, setGate] = useState<GateState>(IDLE_GATE);
  const [pendingId, setPendingId] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .downloadsStatus()
      .then((s) => !cancelled && setManifest(s))
      .catch(() => !cancelled && setManifestEnabled(false));
    return () => {
      cancelled = true;
    };
  }, []);

  const statusById = useMemo(
    () => new Map((manifest?.targets || []).map((t) => [t.target_id, t])),
    [manifest]
  );
  const installedIds = useMemo(() => new Set(targets.map((t) => t.target_id)), [targets]);

  const kindsNeeded = (id: string): Kind[] => {
    const row = statusById.get(id);
    if (!row) return [];
    return need.filter((k) => row[k].available && !row[k].installed);
  };

  /** True if selecting `id` right now would commit immediately (no
      download needed) — used both to fast-path a real selection and to
      decide whether auto-picking a default on mount is safe (never
      auto-trigger a download just because a tab was opened). */
  const isReady = (id: string): boolean => {
    if (installedIds.has(id)) return true;
    if (!manifestEnabled) return false;
    const row = statusById.get(id);
    return row ? kindsNeeded(id).length === 0 : false;
  };

  const select = async (id: string) => {
    const missing = manifestEnabled ? kindsNeeded(id) : [];
    if (!missing.length) {
      setPendingId(null);
      setGate(IDLE_GATE);
      onReady(id);
      return;
    }
    setPendingId(id);
    try {
      for (const kind of missing) {
        setGate({ active: true, kind, done: 0, total: 0, error: null });
        await api.ensureDownloaded(id, kind, (p) =>
          setGate({ active: true, kind, done: p.done, total: p.total, error: null })
        );
      }
      setGate(IDLE_GATE);
      setPendingId(null);
      refresh();
      onReady(id);
    } catch (e: any) {
      setGate((g) => ({ ...g, active: false, error: e.message || "Download failed." }));
    }
  };

  const retry = () => {
    if (pendingId) select(pendingId);
  };

  const downloadHint = (id: string): string => {
    if (isReady(id)) return "";
    const row = statusById.get(id);
    const size = row?.model.size;
    return ` — ⬇ download${size ? ` (${fmtBytes(size)})` : ""}`;
  };

  // Real (non-GENE_) targets the manifest knows about but that aren't
  // installed locally yet — merged into the default (non-disease-
  // filtered) option list so a user can pick and auto-download one
  // without ever visiting the Downloads tab.
  const downloadableExtraIds = useMemo(() => {
    if (!manifestEnabled || !manifest) return [];
    return manifest.targets
      .filter((t) => t.model.available && !installedIds.has(t.target_id))
      .map((t) => t.target_id);
  }, [manifest, manifestEnabled, installedIds]);

  return { gate, pendingId, select, retry, isReady, downloadHint, downloadableExtraIds };
}

function DownloadGateBar({ gate, onRetry }: { gate: GateState; onRetry: () => void }) {
  if (gate.error) {
    return (
      <div className="field-hint">
        <span className="text-clay">{gate.error}</span>{" "}
        <button type="button" className="font-semibold text-brand-700 underline" onClick={onRetry}>
          Retry
        </button>
      </div>
    );
  }
  if (!gate.active) return null;
  const pct = gate.total ? Math.round((100 * gate.done) / gate.total) : 0;
  return (
    <div className="mt-1.5">
      <div className="h-1.5 overflow-hidden rounded-full bg-surface2">
        <div className="h-full rounded-full bg-brand-500 transition-all duration-300" style={{ width: `${pct}%` }} />
      </div>
      <div className="mt-1 text-[11.5px] text-inkmut">
        Downloading {gate.kind === "docking" ? "docking data" : "model"}… {pct}%
        {gate.total ? ` (${fmtBytes(gate.done)} of ${fmtBytes(gate.total)})` : ""}
      </div>
    </div>
  );
}

/** Disease filter + target select, shared by Screen and Docking — mirrors
    populateGroupTargets()/populateScreenTargets()/populateDockTargets() from
    the original app: picking a disease re-ranks the target list and may
    introduce synthetic GENE_<symbol> ids for proteins with disease evidence
    but no trained QSAR model (docking-only).

    `need` declares which data kind(s) the calling tab actually requires
    present before it can use a target — e.g. Screen needs both the QSAR
    model and the docking receptor, Docking needs only the receptor. A
    target missing something in `need` auto-downloads it inline (see
    useDownloadGate above) before onChange fires. */
export function TargetPicker({
  targetId,
  onChange,
  need = ["model"],
}: {
  targetId: string;
  onChange: (id: string) => void;
  need?: Kind[];
}) {
  const { targets, diseases } = useAppData();
  const [diseaseId, setDiseaseId] = useState("");
  const [ranked, setRanked] = useState<DiseaseTarget[] | null>(null);
  const gateApi = useDownloadGate(need, onChange);

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
    ? ranked.map((t) => {
        const value = t.has_qsar_model ? t.target_id! : "GENE_" + t.target_symbol;
        const base = t.has_qsar_model
          ? `${t.validated ? "✓" : "⚠"} ${t.target_symbol} (${t.target_id}) — score ${t.disease_score}`
          : `⚙ ${t.target_symbol} — score ${t.disease_score} (no QSAR model — docking only)`;
        return { value, label: base + gateApi.downloadHint(value) };
      })
    : [
        ...targets.map((t) => ({ value: t.target_id, label: t.target_id })),
        ...gateApi.downloadableExtraIds.map((id) => ({ value: id, label: `${id}${gateApi.downloadHint(id)}` })),
      ];

  const optionKey = options.map((o) => o.value).join("|");
  useEffect(() => {
    if (!options.length) {
      if (targetId) onChange("");
      return;
    }
    if (!options.find((o) => o.value === targetId)) {
      // Only ever auto-pick something already usable — opening a tab must
      // never silently kick off a multi-GB download on its own.
      const ready = options.find((o) => gateApi.isReady(o.value));
      if (ready) gateApi.select(ready.value);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [optionKey]);

  const current = targets.find((t) => t.target_id === targetId);
  const geneOnly = targetId.startsWith("GENE_");
  const selectValue = gateApi.pendingId ?? targetId;

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
