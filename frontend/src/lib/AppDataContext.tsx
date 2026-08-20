import { createContext, useCallback, useContext, useEffect, useState } from "react";
import * as api from "./api";
import type { DiseaseSummary, DockingStatus, TargetMeta } from "./types";

interface AppData {
  loading: boolean;
  error: string | null;
  targetCount: number;
  targets: TargetMeta[];
  diseases: DiseaseSummary[];
  dockingStatus: DockingStatus | null;
  admetAvailable: boolean;
  /** Re-fetches targets/diseases/docking status without a full page reload
      — called by the Downloads tab after a target bucket finishes
      downloading, so the newly-installed target shows up in TargetPicker
      etc. without the user needing to relaunch the app. */
  refresh: () => void;
}

const NOOP_DATA: AppData = {
  loading: true,
  error: null,
  targetCount: 0,
  targets: [],
  diseases: [],
  dockingStatus: null,
  admetAvailable: false,
  refresh: () => {},
};

const Ctx = createContext<AppData>(NOOP_DATA);

export function AppDataProvider({ children }: { children: React.ReactNode }) {
  const [data, setData] = useState<Omit<AppData, "refresh">>(NOOP_DATA);

  const load = useCallback(async () => {
    try {
      const [h, t] = await Promise.all([api.health(), api.listTargets()]);
      let diseases: DiseaseSummary[] = [];
      try {
        diseases = (await api.listDiseases()).diseases;
      } catch {
        /* optional */
      }
      let dockingStatus: DockingStatus | null = null;
      try {
        dockingStatus = await api.dockingStatus();
      } catch {
        /* optional */
      }
      setData({
        loading: false,
        error: null,
        targetCount: h.targets_in_bucket_dir,
        targets: t.targets,
        diseases,
        dockingStatus,
        admetAvailable: h.admet_ai,
      });
    } catch (e: any) {
      setData((d) => ({ ...d, loading: false, error: e.message || "backend error" }));
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  return <Ctx.Provider value={{ ...data, refresh: load }}>{children}</Ctx.Provider>;
}

export const useAppData = () => useContext(Ctx);
