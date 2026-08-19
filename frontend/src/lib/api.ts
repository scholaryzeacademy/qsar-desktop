import type {
  AdmetResponse,
  AdvancedDockingBody,
  BindingSiteResponse,
  BucketFile,
  CompareResponse,
  DiseaseSummary,
  DiseaseTarget,
  DockJobStatus,
  DockingStatus,
  PredictResponse,
  ReceptorProfile,
  RecommendationResponse,
  ScreenJobStatus,
  StructureCandidatesResponse,
  TargetMeta,
} from "./types";

class ApiError extends Error {}

/** Backend base URL. Empty string keeps requests relative — fine for `npm
    run dev`'s Vite proxy (see vite.config.ts) or a same-origin deployment
    behind a reverse proxy. Set VITE_API_BASE at build time (e.g.
    `VITE_API_BASE=http://localhost:8000 npm run build`) to talk to a
    backend running as its own separate service/origin; the backend's CORS
    (see backend/app.py's ALLOWED_ORIGINS) must allow the frontend's origin
    for that to work. */
export const API_BASE = (import.meta.env.VITE_API_BASE ?? "").replace(/\/$/, "");
export const apiUrl = (path: string) => `${API_BASE}${path}`;

async function api<T>(path: string, opts?: RequestInit): Promise<T> {
  const res = await fetch(apiUrl(path), opts);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new ApiError(data.detail || "Error");
  return data as T;
}

const json = (body: unknown): RequestInit => ({
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

export const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

/** Wraps one poll-loop request with retries for TRANSIENT network failures
    (a dropped SSH tunnel hop, a brief wifi blip) — long-running jobs (Screen,
    Docking, Fresh Decoy Validation) poll every couple seconds for anywhere
    from tens of seconds to tens of minutes, and over that span a single
    fetch() rejecting outright ("Failed to fetch") used to kill the whole
    operation on the very first hiccup. Retries a few times with backoff
    before finally propagating — a REAL failure (job genuinely gone, server
    down) still surfaces, just not on the first transient blip. Only wraps
    the polling GET, never the initiating POST (that one should fail fast —
    it's a direct user action, not a long background wait). */
export async function pollRetry<T>(fn: () => Promise<T>, retries = 4, delayMs = 3000): Promise<T> {
  let lastErr: unknown;
  for (let i = 0; i <= retries; i++) {
    try {
      return await fn();
    } catch (e) {
      lastErr = e;
      if (i < retries) await sleep(delayMs);
    }
  }
  throw lastErr;
}

// ---------- shared ----------
export const health = () =>
  api<{ targets_in_bucket_dir: number; admet_ai: boolean; docking: string; disclaimer: string }>("/api/health");
export const listTargets = () => api<{ targets: TargetMeta[] }>("/api/targets");
export const listDiseases = () => api<{ diseases: DiseaseSummary[] }>("/api/diseases");
export const targetsForDisease = (diseaseId: string) =>
  api<{ targets: DiseaseTarget[] }>(`/api/diseases/${encodeURIComponent(diseaseId)}/targets`);
export const parseSdf = async (file: File): Promise<{ smiles: string[] }> => {
  const fd = new FormData();
  fd.append("file", file);
  return api("/api/parse_sdf", { method: "POST", body: fd });
};

// ---------- predict ----------
export const predict = (target_id: string, smiles: string[]) =>
  api<PredictResponse>("/api/predict", json({ target_id, smiles }));

// ---------- admet ----------
export const admet = (smiles: string[]) => api<AdmetResponse>("/api/admet", json({ target_id: "_", smiles }));
export const admetJob = (jid: string) => api<AdmetResponse>(`/api/admet/job/${jid}`);

// ---------- compare ----------
export const predictMulti = (smiles: string[], target_ids: string[]) =>
  api<CompareResponse>("/api/predict_multi", json({ smiles, target_ids }));

// ---------- target recommendation / info ----------
export const targetRecommendation = (targetId: string) =>
  api<RecommendationResponse>(`/api/targets/${targetId}/recommendation`);
export const factoryMetrics = (targetId: string) =>
  api<{ target_id: string; metrics: Record<string, any> }>(`/api/factory/target/${targetId}/metrics`);
export const factoryBucket = (targetId: string) =>
  api<{ target_id: string; n_files: number; files: BucketFile[] }>(`/api/factory/bucket/${targetId}`);

// ---------- docking status / registry ----------
export const dockingStatus = () => api<DockingStatus>("/api/docking/status");

// ---------- binding site / structures ----------
export const bindingSite = (targetId: string) => api<BindingSiteResponse>(`/api/targets/${targetId}/binding_site`);
export const structureCandidates = (targetId: string) =>
  api<StructureCandidatesResponse>(
    targetId.startsWith("GENE_")
      ? `/api/genes/${encodeURIComponent(targetId.slice(5))}/structure_candidates`
      : `/api/targets/${targetId}/structure_candidates`
  );
export const boxFromResidues = (body: {
  target_id: string;
  residues: { chain: string; resnum: number }[];
  receptor_pdb?: string | null;
  padding?: number;
}) => api<{ center: [number, number, number]; box_size: [number, number, number] }>("/api/docking/box_from_residues", json(body));

export const receptorFile = (path: string) =>
  fetch(apiUrl(`/api/docking/receptor_file?path=${encodeURIComponent(path)}`)).then((r) => r.text());
export const receptorForTarget = (targetId: string) =>
  fetch(apiUrl(`/api/docking/receptor/${targetId}`)).then((r) => r.text());
export const referenceLigandSdf = (targetId: string) =>
  fetch(apiUrl(`/api/targets/${targetId}/reference_ligand.sdf`)).then((r) => r.text());

// ---------- custom receptor + auto-validate (async jobs) ----------
export const submitCustomReceptor = (body: { target_id: string; pdb_id: string; ligand_resname?: string }) =>
  api<{ job_id: string }>("/api/docking/receptor/custom", json(body));
export const customReceptorJob = (jid: string) =>
  api<{ status: string; profile?: ReceptorProfile; error?: string }>(`/api/docking/receptor/custom/job/${jid}`);

export const submitAutoValidate = (target_id: string) =>
  api<{ job_id: string }>("/api/docking/receptor/auto_validate", json({ target_id }));
export const autoValidateJob = (jid: string) =>
  api<{
    status: string;
    error?: string;
    result?: {
      was_already_validated: boolean;
      prior_pdb_source?: string | null;
      prior_reference_rmsd?: number | null;
      validated: boolean;
      pdb_source?: string | null;
      reference_rmsd?: number | null;
      changed: boolean;
    };
  }>(`/api/docking/receptor/auto_validate/job/${jid}`);

// ---------- docking submit / poll ----------
export const submitDocking = (target_id: string, smiles: string[], advanced: AdvancedDockingBody | null) =>
  api<{ job_id: string; total: number; caveat?: string | null }>("/api/docking/submit", json({ target_id, smiles, advanced }));
export const dockingJob = (jid: string) => api<DockJobStatus>(`/api/docking/job/${jid}`);

// ---------- fresh decoy validation ----------
export const submitFreshDecoy = (target_id: string, smiles: string, advanced: AdvancedDockingBody | null) =>
  api<{ job_id: string }>("/api/docking/enrichment/fresh", json({ target_id, smiles, advanced }));
export const freshDecoyJob = (jid: string) =>
  api<{
    status: string;
    done: number;
    total: number;
    error?: string;
    result?: {
      error?: string;
      percentile: number;
      discrimination: string;
      compound_score: number;
      n_decoys_docked: number;
      n_decoys_failed?: number;
    };
  }>(`/api/docking/enrichment/fresh/job/${jid}`);

// ---------- screen pipeline ----------
export const submitScreen = (target_id: string, smiles: string[], advanced: AdvancedDockingBody | null) =>
  api<{ job_id: string }>("/api/screen/submit", json({ target_id, smiles, advanced }));
export const screenJob = (jid: string) => api<ScreenJobStatus>(`/api/screen/job/${jid}`);
export const screenExportUrl = (jid: string) => apiUrl(`/api/screen/job/${jid}/export.csv`);

export { ApiError };
