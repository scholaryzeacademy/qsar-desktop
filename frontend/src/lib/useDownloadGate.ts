import { useEffect, useMemo, useState } from "react";
import { useAppData } from "./AppDataContext";
import * as api from "./api";
import { fmtBytes } from "./format";
import type { DownloadsStatus } from "./types";

export type Kind = "model" | "docking";

export interface GateState {
  active: boolean;
  kind: Kind | null;
  done: number;
  total: number;
  error: string | null;
  jobId: string | null;
}

export const IDLE_GATE: GateState = { active: false, kind: null, done: 0, total: 0, error: null, jobId: null };

/** Shared by every target-selection UI (TargetBrowser, PlainTargetSelect):
    makes the picker manifest-aware (the option list can include real
    targets that aren't downloaded yet, see backend/downloads.py) and
    gates a selection behind an inline auto-download — the caller's
    onChange only ever fires once the target's data for `need` actually
    exists on disk, so every consuming tab keeps working exactly as it
    does today with zero changes of its own.

    Falls back to pure pass-through (today's exact behavior) if the
    downloads manifest is unavailable (DOWNLOAD_BASE_URL unset, or the
    split web deployment) — `manifestEnabled` stays false and nothing
    below ever triggers. */
export function useDownloadGate(need: Kind[], onReady: (id: string) => void) {
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
        setGate({ active: true, kind, done: 0, total: 0, error: null, jobId: null });
        await api.ensureDownloaded(
          id,
          kind,
          (p) => setGate((g) => ({ active: true, kind, done: p.done, total: p.total, error: null, jobId: g.jobId })),
          (jobId) => setGate((g) => ({ ...g, jobId }))
        );
      }
      setGate(IDLE_GATE);
      setPendingId(null);
      refresh();
      onReady(id);
    } catch (e: any) {
      setGate((g) => ({ ...g, active: false, error: e.message || "Download failed.", jobId: null }));
    }
  };

  const retry = () => {
    if (pendingId) select(pendingId);
  };

  const stop = async () => {
    if (!gate.jobId) return;
    try {
      await api.cancelDownload(gate.jobId);
    } catch {
      /* the poll loop will still surface a final status either way */
    }
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

  return { gate, pendingId, select, retry, stop, isReady, downloadHint, downloadableExtraIds };
}
