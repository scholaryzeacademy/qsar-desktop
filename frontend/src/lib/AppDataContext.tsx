import { createContext, useContext, useEffect, useState } from "react";
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
}

const Ctx = createContext<AppData>({
  loading: true,
  error: null,
  targetCount: 0,
  targets: [],
  diseases: [],
  dockingStatus: null,
  admetAvailable: false,
});

export function AppDataProvider({ children }: { children: React.ReactNode }) {
  const [data, setData] = useState<AppData>({
    loading: true,
    error: null,
    targetCount: 0,
    targets: [],
    diseases: [],
    dockingStatus: null,
    admetAvailable: false,
  });

  useEffect(() => {
    (async () => {
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
    })();
  }, []);

  return <Ctx.Provider value={data}>{children}</Ctx.Provider>;
}

export const useAppData = () => useContext(Ctx);
