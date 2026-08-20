// Loose but useful TypeScript shapes mirroring app.py's JSON responses.
// Deeply-variable nested payloads (docking results, ADMET learned groups,
// compare views) are typed permissively — the UI reads through them
// defensively exactly like the original vanilla-JS client did.

export interface TargetMeta {
  target_id: string;
  name?: string;
  best_model?: string | null;
  n_compounds?: number | null;
  test_r2?: number | null;
  test_rmse?: number | null;
  ad_coverage_pct?: number | null;
  tropsha_pass?: boolean | null;
}

export interface DiseaseSummary {
  disease_id: string;
  name: string;
  is_therapeutic_area?: boolean;
}

export interface DiseaseTarget {
  target_id?: string;
  target_symbol: string;
  has_qsar_model: boolean;
  validated?: boolean;
  disease_score: number | string;
}

export type Confidence = "high" | "med" | "low" | "out" | "na";

export interface QsarRow {
  input_smiles?: string;
  smiles?: string;
  parsed_ok?: boolean;
  predicted_pIC50?: number | null;
  in_domain: boolean;
  ad_z?: number | null;
  confidence?: Confidence;
  confidence_label?: string;
  confidence_basis?: string;
  rank?: number;
}

export interface PredictResponse {
  target: { id: string; name: string };
  model?: string | null;
  model_metrics: {
    test_r2?: number | null;
    test_rmse?: number | null;
    pearson_r?: number | null;
    ad_coverage_pct?: number | null;
    tropsha_pass?: boolean | null;
    y_random_delta_r2?: number | null;
  };
  counts: { in_domain: number; out_of_domain: number; skipped: number; submitted: number };
  in_domain: QsarRow[];
  out_of_domain: QsarRow[];
  skipped: string[];
  disclaimer: string;
}

export interface AdmetProfile {
  input_smiles: string;
  standardised_smiles?: string;
  parsed_ok: boolean;
  physicochemical?: { mw: number; logp: number; qed: number };
  drug_likeness_flags?: { lipinski_pass: boolean; lipinski_violations: number };
  n_alerts?: number;
  learned?: {
    available: boolean;
    note?: string;
    flags?: any[];
    groups?: Record<string, { label: string; display: string; tone: string; percentile?: number | null }[]>;
  };
}

export interface AdmetResponse {
  mode?: "result" | "job";
  job_id?: string;
  total?: number;
  status?: string;
  done?: number;
  profiles: AdmetProfile[];
  learned: { available: boolean; note?: string };
  disclaimer: string;
}

export interface CompareResponse {
  disclaimer: string;
  targets: { target_id: string }[];
  matrix: { smiles?: string; input_smiles?: string; cells: Record<string, { pred: number | null; in_domain: boolean }>; coverage: { in_domain_targets: number; total_targets: number } }[];
  consensus_ranking: { consensus_rank: number; smiles: string; n_active: number; mean_pred: number; coverage: string }[];
  selective_candidates: { smiles: string; target: string; pred: number; gap: number }[];
  selective_gap: number;
  multi_target_candidates: { smiles: string; active_targets: string[]; n_active: number; mean_pred: number }[];
  active_cut: number;
  best_per_target: Record<string, { smiles: string; pred: number }[]>;
  admet: Record<string, AdmetProfile>;
}

export interface AdvancedDockingBody {
  exhaustiveness?: number | null;
  n_poses?: number | null;
  use_gnina?: boolean | null;
  docking_mode?: "site_specific" | "blind" | null;
  box_center?: [number, number, number] | null;
  box_size?: [number, number, number] | null;
  custom_profile?: ReceptorProfile | null;
}

export interface ReceptorProfile {
  target_id?: string;
  receptor_pdb: string;
  center: [number, number, number];
  box_size: [number, number, number];
  validated?: boolean;
  reference_rmsd?: number | null;
  redock_note?: string;
  pdb_source?: string;
  binding_site_residues?: PocketResidue[];
  blind_center?: [number, number, number];
  blind_box_size?: [number, number, number];
  [k: string]: any;
}

export interface PocketResidue {
  chain: string;
  resnum: number;
  resname: string;
}

export interface BindingSiteResponse {
  target_id: string;
  center?: [number, number, number];
  box_size?: [number, number, number];
  reference_ligand_resname?: string;
  pocket_residues: PocketResidue[];
  n_pocket_residues: number;
  has_reference_ligand_mol: boolean;
  blind_center?: [number, number, number];
  blind_box_size?: [number, number, number];
  error?: string | null;
}

export interface StructureCandidate {
  pdb_id: string;
  resname: string;
  csv_rank: number | null;
  is_current_default: boolean;
  resolution?: number | null;
  ligand_RSCC?: number | null;
  ligand_RSR?: number | null;
}

export interface StructureCandidatesResponse {
  target_id?: string;
  gene: string;
  default_pdb_id: string | null;
  candidates: StructureCandidate[];
  n_qualifying_structures?: number | null;
  note?: string;
}

export interface DockResultRow {
  smiles: string;
  status: string;
  reason?: string;
  confidence?: "high" | "medium" | "low" | "none";
  vina_score?: number | null;
  n_valid?: number;
  gnina?: { cnn_score?: number | null; cnn_affinity?: number | null; gnina_affinity?: number | null };
  interaction_png?: string | null;
  interaction_source?: string;
  residue_overlap_pct?: number | null;
  interactions?: { name?: string; residue?: string; category?: string; label?: string; type?: string; distance?: number }[];
  pose_pdb?: string | null;
  enrichment_percentile?: number | null;
  enrichment_context?: { n_active?: number; n_decoy?: number; decoy_method?: string; beats_best_known_active?: boolean };
}

export interface DockJobDone {
  status: "done";
  done: number;
  total: number;
  caveat?: string | null;
  results: DockResultRow[];
  receptor_pdb_path?: string | null;
}
export interface DockJobPending {
  status: "queued" | "running";
  done: number;
  total: number;
  caveat?: string | null;
}
export interface DockJobError {
  status: "error";
  error?: string;
}
export type DockJobStatus = DockJobDone | DockJobPending | DockJobError;

export interface ScreenShortlistRow {
  rank: number;
  input_smiles: string;
  smiles: string;
  qsar: QsarRow & { in_domain: boolean };
  docking: DockResultRow | null;
  fused_score?: number | null;
  caveats: string[];
}

export interface ScreenResult {
  target_id: string;
  counts: { submitted: number; parsed: number; skipped: number };
  methods_note: string;
  docking_used: boolean;
  docking_note?: string;
  shortlist: ScreenShortlistRow[];
  skipped: string[];
  receptor_pdb_path?: string | null;
}

export interface ScreenJobStatus {
  status: "queued" | "running" | "done" | "error";
  step?: number;
  step_label?: string;
  total_steps?: number;
  done?: number | null;
  total?: number | null;
  result?: ScreenResult;
  error?: string;
}

export interface RecommendationResponse {
  headline: string;
  our_validation: {
    validated: boolean;
    reference_rmsd?: number | null;
    enrichment_auc?: number | null;
    pdb_id?: string;
    ligand_resname?: string;
  };
  panel_evidence: {
    top_ranked_pdb_id?: string;
    top_ranked_chain?: string;
    top_ranked_ligand?: string;
    resolution?: number | null;
    resolution_tier?: string;
    ligand_RSCC?: number | null;
    ligand_RSR?: number | null;
    r_free?: number | null;
    n_qualifying_structures?: number | null;
    chembl_activity_records?: number | null;
    note?: string;
  };
}

export interface DockingStatus {
  ready: boolean;
  note?: string;
  import_error?: string;
  packages?: Record<string, boolean>;
  package_desc?: Record<string, string>;
  binaries?: Record<string, boolean>;
  binary_desc?: Record<string, string>;
  planned?: string[];
  docking_targets?: string[];
  target_details?: {
    target_id: string;
    name: string;
    validated: boolean;
    reference_rmsd?: number | null;
    enrichment_auc?: number | null;
    enrichment_ef20?: number | null;
    enrichment_n?: number | null;
    site_source?: string;
  }[];
}

export interface BucketFile {
  path: string;
  name: string;
  bytes: number;
  annotation?: string;
  category: string;
}

// ---------- on-demand downloads (Downloads tab) ----------
export interface DownloadKindStatus {
  available: boolean;
  installed: boolean;
  size?: number;
}
export interface DownloadTargetRow {
  target_id: string;
  model: DownloadKindStatus;
  docking: DownloadKindStatus;
}
export interface DownloadsStatus {
  download_base_url: string | null;
  targets: DownloadTargetRow[];
}
export interface DownloadStartResponse {
  job_id: string | null;
  already_installed?: boolean;
}
export interface DownloadJobStatus {
  target_id: string;
  kind: "model" | "docking";
  state: "starting" | "downloading" | "extracting" | "done" | "error";
  done: number;
  total: number;
  error?: string | null;
}
