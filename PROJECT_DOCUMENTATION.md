# PhytoScreen Desktop — Project Documentation

**A local, offline, CPU-only desktop application for prioritising chemical compounds against validated biological drug targets.**

Prepared: 2026-08-08

---

## 1. Overview

PhytoScreen Desktop is a self-contained research tool that takes one or more molecules (as SMILES strings) and evaluates them against a panel of **52 biological drug targets** (kinases, proteases, nuclear receptors, GPCRs-related enzymes, etc.), producing:

1. A **predicted potency** (pIC50) against each target, from a machine-learned QSAR model trained on real ChEMBL bioactivity data.
2. An **ADMET liability profile** (absorption, distribution, metabolism, excretion, toxicity) combining fast deterministic rules with an optional learned model.
3. A **structure-based docking** estimate (AutoDock Vina) — a 3D physical pose and binding-affinity score against the target's crystal structure, for targets where the receptor has been prepared and validated.
4. A ranked, evidence-annotated shortlist that fuses all of the above, with every claim traceable to a real number and every caveat stated explicitly.

The whole system runs **locally, with no internet dependency at inference time, on CPU only** (no GPU required to *use* the app — GPU was used only to *train* the underlying QSAR models). It ships as a native desktop window (PyWebview) wrapping a FastAPI backend, or can be built into a standalone Windows `.exe` (PyInstaller).

The guiding design principle throughout the codebase is what its own internal documentation calls **"calibrated honesty"**: the application never fabricates a number it cannot support. Confidence tiers are derived from real held-out test error, not an invented interval; out-of-domain predictions are shown but explicitly not trusted; docking targets are only marked "validated" after passing a real geometric reproducibility test; and every metric a user sees traces back to a specific file in a specific target's training bucket, downloadable from the app itself.

---

## 2. Objectives

1. **Prioritise** candidate compounds (e.g. natural-product or synthetic libraries) against a panel of real, pharmacologically relevant targets, without requiring a wet lab, a GPU, or an internet connection.
2. **Make every prediction inspectable.** A researcher (or their reviewer) should be able to trace any number back to the model that produced it, the data it was trained on, and the validation evidence for that model — not treat the tool as a black box.
3. **Never silently overstate confidence.** Predictions outside a model's training chemistry, targets whose docking receptor hasn't been geometrically validated, and ADMET flags are all surfaced as caveats attached to the result, not filtered out or hidden.
4. **Combine two independent lines of evidence** (ligand-based QSAR potency and structure-based docking) so a compound's ranking isn't dependent on a single method's blind spots.
5. **Be practically deployable** to a non-technical end user (a single native desktop window, one `.exe`, no server to manage).

---

## 3. System Architecture

```
                    ┌─────────────────────────┐
                    │   desktop.py (PyWebview) │  native window, launches the backend
                    └────────────┬────────────┘
                                 │
                    ┌────────────▼────────────┐
                    │   app.py (FastAPI)       │  mounts every feature as a REST API
                    └───┬────┬────┬────┬───┬──┘
       ┌────────────────┘    │    │    │   └───────────────┐
       ▼                     ▼    ▼    ▼                   ▼
┌─────────────┐   ┌──────────────┐  ┌────────────┐  ┌──────────────┐
│ serving/     │   │ admet.py +   │  │ docking/   │  │ factory_      │
│ (QSAR)       │   │ admet_       │  │ (Vina +    │  │ browser.py    │
│ model_adapter│   │ service.py   │  │ PoseBusters│  │ (Target Info  │
│ featurize    │   │ (worker      │  │ + GNINA)   │  │ tab: browse / │
│ applicability│   │ process)     │  │            │  │ download every│
│ confidence   │   │              │  │            │  │ bucket file)  │
│ screen.py    │   └──────────────┘  └────────────┘  └──────────────┘
└──────┬───────┘
       │  reads
       ▼
┌─────────────────────────────┐      ┌──────────────────────────┐
│ models/<target_id>/          │      │ docking_targets/<id>/     │
│ per-target QSAR bucket        │      │ prepared receptor PDBQT  │
│ (AutoGluon + Chemprop,       │      │ + docking_registry.json  │
│ read-only, 101 GB / 52 tgts) │      │ (validated / unvalidated)│
└─────────────────────────────┘      └──────────────────────────┘

                    ┌─────────────────────────┐
                    │ static/index.html        │  single-page UI:
                    │ (vanilla JS, no build     │  Screen / Predict / ADMET /
                    │  step)                    │  Compare / Docking / Target Info
                    └─────────────────────────┘
```

**Key architectural rule (enforced by module boundaries):** `serving/model_adapter.py` is the *only* module that imports AutoGluon or Chemprop directly. Everything else calls `load_target()` / `Target.predict_smiles()`. Similarly, `docking/` is the only place that imports RDKit-for-docking, Meeko, PoseBusters, or subprocess-calls Vina. This isolation means a failure or absence of one heavy dependency (e.g. no GPU, no Vina binary, no ADMET-AI installed) degrades that one feature gracefully instead of crashing the whole app.

### 3.1 Component inventory

| Component | Responsibility |
|---|---|
| `desktop.py` | Launches the FastAPI backend on a free local port in a background thread, waits for `/api/health`, opens a native PyWebview window pointed at it. Falls back to printing a plain `http://localhost:PORT/` URL if no native GUI backend is available. |
| `app.py` | FastAPI app; defines every REST endpoint (`/api/predict`, `/api/admet`, `/api/predict_multi`, `/api/docking/*`, `/api/screen`, `/api/targets`, `/api/health`) and mounts `factory_browser`'s router and the static UI. |
| `serving/model_adapter.py` | Loads a target's model bucket (AutoGluon `TabularPredictor` + Chemprop D-MPNN checkpoint), runs the two-stage inference pipeline, applies the applicability-domain gate and confidence tiering. Bounded LRU cache (default 2 targets in memory at once — buckets are large). |
| `serving/featurize.py` | SMILES → the exact feature space the models were trained on (RDKit 2D descriptors by name + MACCS keys + Morgan/ECFP4 fingerprint). Includes a startup **self-check** that asserts every column a target's model expects can actually be produced, so a descriptor-naming drift fails loudly instead of silently zero-filling and corrupting predictions. |
| `serving/applicability.py` | Applicability-domain (AD) gate: mean absolute z-score of a query molecule's features against the target's own training-set feature statistics. Above threshold (default 3.0) → "out of domain", never given a trusted potency number. |
| `serving/confidence.py` | Maps (in-domain?, target's held-out test RMSE) → a confidence tier (`high`/`med`/`low`/`out`) with a human-readable, honestly-labelled basis string. |
| `serving/screen.py` | The 8-step Screen pipeline orchestrator (§4.7). |
| `analysis.py` | Multi-target "Compare" analysis: potency matrix, selectivity, polypharmacology, consensus ranking (§4.8). |
| `admet.py` / `admet_endpoints.py` / `admet_service.py` | Two-layer ADMET profiling: always-on deterministic rules (RDKit) + an optional learned layer (ADMET-AI) that runs in an isolated worker process so it can never freeze the main app (§4.5). |
| `docking/` (10 modules) | Full structure-based docking stack: receptor preparation, ligand preparation, the Vina engine, the PoseBusters physical-validity gate, pose consensus/confidence, optional GNINA CNN rescoring, and 2D interaction diagrams (§4.6). |
| `factory_browser.py` | `/api/factory/*` — lists, annotates, and serves (individually or as one zip) every file in a target's training bucket, so the underlying evidence for any metric is always one click away ("Target Info" tab). |
| `static/index.html` | The entire frontend: one hand-written HTML/CSS/vanilla-JS file (no build step, no framework), with six tabs — Screen, Predict, ADMET, Compare, Docking, Target Info. |
| `models/<target_id>/` | Per-target, read-only training output (see §6). Not shipped in source control (101 GB); the app reads it directly. |
| `docking_targets/<target_id>/` + `docking_registry.json` | Prepared receptors (PDBQT + cleaned PDB) and their validation record (center/box, reference RMSD, enrichment AUC, `validated: true/false`). |

---

## 4. Core Methods & Logic

### 4.1 QSAR potency prediction — two-stage model

Each target's potency model is a **two-stage pipeline**, confirmed from the training run logs (not just the simplified description in the app's own comments):

1. **Stage 1 — Chemprop D-MPNN.** A directed message-passing graph neural network runs directly on the molecular graph (no hand-crafted features) and outputs one number: `chemprop_pred`.
2. **Stage 2 — AutoGluon stacked ensemble.** `chemprop_pred` is appended as one more tabular feature alongside ~2,300 RDKit 2D descriptors + MACCS keys + Morgan/ECFP4 bits (after per-target feature selection), and the full vector is fed to an AutoGluon `TabularPredictor` — a multi-layer stacked ensemble of LightGBM, LightGBM-XT, CatBoost, RandomForest, ExtraTrees, and a weighted meta-ensemble on top (visible per-target under `chosen_model/models/`).

Both stages are **inference-only** at serving time — no training happens in the desktop app; training happened once, offline, on a GPU machine, and the resulting artifacts are shipped as a read-only "bucket." Inference is forced CPU-only (`accelerator="cpu"`, thread counts capped) regardless of what hardware is available, so the desktop app never needs or touches a GPU.

**Why two stages instead of one:** the training metadata for every target records `Chemprop_Alone_R2` alongside the final ensemble's `R2_Test` — for BRD4, for example, Chemprop alone reaches R² 0.749, while the full two-stage pipeline reaches R² 0.801. Stacking the graph model's prediction as a feature into the tabular ensemble measurably improves over either approach alone.

### 4.2 Featurisation (`serving/featurize.py`)

SMILES → standardised SMILES (RDKit cleanup + largest-fragment + uncharge, identical to what the training factory used) → a feature dictionary of:
- All RDKit `Descriptors.descList` values (~217 named 2D descriptors), each individually try/excepted with a `0.0` fallback so one bad descriptor never fails the whole molecule;
- 167 MACCS keys (`MACCS_0`...`MACCS_166`);
- 2048-bit Morgan/ECFP4 fingerprint, radius 2 (`Morgan_0`...`Morgan_2047`).

This is described in the code as **"the single most important correctness boundary in the app"** — a silent naming or ordering mismatch here would corrupt every prediction without any visible error. To guard against that, `self_check()` runs once per target at load time: it featurises a known molecule (aspirin) and asserts every column the target's `selected_features.csv` expects is actually produced. If a future RDKit version renames or removes a descriptor, the app refuses to serve predictions rather than silently zero-filling the missing columns.

### 4.3 Applicability Domain (AD)

A compound is only given a trusted potency number if it falls inside the target's training chemistry. Concretely: per-feature mean and standard deviation are computed once from the target's own `Data/fit.csv` (the exact rows the shipped model was fit on); a query molecule's mean absolute z-score across all features is computed, and compounds with mean |z| > 3.0 are flagged **out of domain** — shown in the UI, but explicitly never counted as evidence in rankings, comparisons, or the Screen shortlist.

### 4.4 Confidence tiers

The shipped AutoGluon models are a single fit/held-out-test split, not a conformal-calibrated ensemble — there is no genuine per-compound prediction interval available. Rather than inventing one, the confidence tier is built from two real, disclosed numbers only:

| Condition | Tier | Basis shown to user |
|---|---|---|
| Out of applicability domain | `out` | "Outside training chemistry" |
| In domain, target's test RMSE ≤ 0.5 pIC50 | `high` | "Held-out test RMSE X.XX pIC50" |
| In domain, target's test RMSE ≤ 1.0 pIC50 | `med` | same |
| In domain, target's test RMSE > 1.0 pIC50 | `low` | same, "wide expected error" |
| In domain, target has no recorded RMSE | `med` | explicitly labelled "unknown", not fabricated |

### 4.5 ADMET profiling — two layers

**Layer 1 — Deterministic (always on, local, instant).** RDKit-computed physicochemical properties (MW, LogP, TPSA, HBD/HBA, rotatable bonds, aromatic rings, fraction sp³, QED) feed four drug-likeness rule sets (Lipinski, Veber, Egan, Ghose) plus three structural-alert catalogs (PAINS, Brenk, NIH). These are explicitly **flags, never filters** — nothing is excluded from results for violating them, since natural products routinely violate Lipinski-style rules while remaining bioactive.

**Layer 2 — Learned (optional, via a separate worker process).** ADMET-AI, a published multi-task model covering dozens of absorption/distribution/metabolism/excretion/toxicity endpoints, runs in `admet_service.py` as an **isolated process** (`uvicorn admet_service:app --port 8100`) specifically so that a heavy or unstable ML stack can never freeze the main serving app. `admet.py` is an HTTP client to that worker: it health-checks it (15 s cache on success, 3 s on failure so the app self-heals within seconds of the worker coming up, no restart needed), and if it's unreachable the deterministic layer is still returned with a clear "learned ADMET unavailable" note rather than an error.

### 4.6 Structure-based docking

The docking stack (10 modules under `docking/`) implements the pipeline **Vina → PoseBusters validity gate → pose consensus → optional GNINA CNN second opinion → 2D interaction diagram**:

1. **Receptor preparation** (`receptor_prep.py`, one-time per target): from a raw PDB with a co-crystallised ligand — extract the reference ligand → strip to protein-only (optionally restricted to one chain) → repair missing atoms/hydrogens with PDBFixer → build the search-box (center + size) from the reference ligand's coordinates + 8 Å padding → convert to a Vina-ready receptor PDBQT via Meeko.
2. **Ligand preparation** (`ligand_prep.py`): SMILES → RDKit 3D embedding (ETKDGv3, multiple seeds retried for strained molecules) → MMFF optimisation → PDBQT via Meeko.
3. **Docking** (`engines.py`, `VinaEngine`): calls the AutoDock Vina binary against the prepared receptor and search box; returns every pose (score + 3D conformer) as an RDKit mol.
4. **Validity gate** (`validity.py`): every pose is run through **PoseBusters** (stereochemistry, bond lengths/angles, ring flatness, internal and protein-ligand clashes) before it is trusted or ranked. This is explicitly a filter, not a scorer — invalid poses are dropped, never down-weighted.
5. **Pose consensus & confidence** (`consensus.py`): the best PoseBusters-valid pose by Vina score is selected; **self-consistency** is measured as how many of Vina's other valid top poses land within 2 Å (atom-map-safe RMSD, see below) of it — a cluster of similar poses is a stronger signal than one isolated low-scoring outlier.
6. **GNINA CNN rescoring** (optional second opinion): if the GNINA binary is present, its convolutional neural network score is combined with self-consistency into a confidence tier (`high`/`medium`/`low`/`none`); **without GNINA, confidence is explicitly capped at `medium`** — documented in the code as intentional, not a missing feature.
7. **Interaction diagram** (`interaction_diagram.py` + `interactions.py`): PLIP (gold-standard interaction typing — H-bond, π-π stacking, hydrophobic, π-cation, salt bridge, halogen bond) if installed; otherwise a built-in RDKit + Biopython distance-based fallback (H-bond/hydrophobic only, explicitly labelled "(distance-based)" in the UI so it never implies a precision it doesn't have). Rendered in a LigPlot+/Discovery-Studio-style 2D schematic.
8. **Atom-map-safe RMSD** (`rmsd.py`): the one non-obvious correctness trap this module exists to close — atom ordering is **not** guaranteed identical across a redocked pose and a reference structure. A naive index-wise RMSD would silently compare mismatched atoms and return a meaningless number. `safe_rmsd()` first hard-asserts the two poses are the same molecule (identical heavy-atom graph, via canonical SMILES with stereo stripped) and only then computes RDKit's `GetBestRMS` (which finds the correct atom mapping over molecular symmetry, not index order). If the molecules don't match, it **refuses to return a number** rather than a wrong one.

**Docking is availability-gated end to end.** If Vina isn't installed, or a target has no validated receptor, the Screen pipeline and Compare views simply omit the docking contribution and say so explicitly (`docking_note`) — QSAR-only results are still returned, never a crash or a silently-missing feature.

### 4.7 The Screen pipeline (`serving/screen.py`) — the headline feature

An explicit, ordered, user-watchable 8-step pipeline that turns a batch of SMILES into a ranked, evidence-annotated shortlist against one target:

| Step | What happens |
|---|---|
| 1 | Parse & standardise every input SMILES (RDKit); unparsable ones are recorded and excluded, never silently dropped |
| 2 | Featurise (folded into step 4's call for efficiency, still reported as its own step) |
| 3 | Applicability-domain check |
| 4 | QSAR potency prediction (two-stage Chemprop+AutoGluon) + confidence tier |
| 5 | ADMET profiling (deterministic + learned if available) |
| 6 | Docking — **only** if the target has a `validated: true` receptor and Vina is available; otherwise skipped with a stated reason |
| 7 | Rank & fuse: QSAR and docking are each converted to a **within-batch rank-based score (0–1)** — deliberately *not* their raw units, since pIC50 and Vina kcal/mol are on incompatible scales and must never be silently averaged as raw numbers. When docking ran, it contributes 35% of the fused score (`DOCK_WEIGHT = 0.35`); otherwise the rank is QSAR-only. |
| 8 | Finalise: attach a plain-English methods/caveats note stating exactly what was and wasn't used and why, per compound |

Every result row carries its own caveats (e.g. "Outside the QSAR model's training chemistry — potency not trusted", "N structural alert(s) — informational, not a filter") so the shortlist is never presented as more certain than the underlying evidence supports.

### 4.8 Multi-target "Compare" analysis (`analysis.py`)

Runs a batch of compounds against several explicitly chosen targets at once and reports:
- **Potency matrix** (compound × target, with in-domain flags and confidence);
- **Selectivity** — gap between a compound's best and second-best in-domain target (≥1.0 log-unit → "selective", otherwise "multi-target");
- **Polypharmacology** — compounds predicted active (pIC50 ≥ 6.0) against 2+ targets simultaneously;
- **Consensus ranking** across all selected targets;
- **Best-per-target** shortlist (top 5 each);
- **ADMET** per compound (deterministic layer).

Ranking uses the point prediction only — the same "no fabricated per-compound interval" honesty rule from §4.4 applies here too, restated explicitly in the returned `disclaimer` field.

*(A previously-present "disease group" shortcut — pre-defined target sets like "Alzheimer's" mapped to `[ache, bche]` — has been removed from both the backend and the UI at the user's request, since it referenced target IDs that didn't correspond to any of the actual 52 model buckets. Compare now always works from an explicit target-ID list.)*

### 4.9 Target Info / factory browser (`factory_browser.py`)

Every metric shown anywhere in the app traces back to a real file the researcher can open. This tab/API lets a user browse, individually download (with a human-readable annotation), or bulk-download-as-zip every file in a target's training bucket: the trained model files, the full metrics record, the training/test data splits, and the 9 standard QSAR diagnostic plots (actual-vs-predicted, residuals, Q-Q, model comparison, Y-randomisation, feature importance, applicability domain, target distribution). This is the mechanism by which "the rigor is visible," not just claimed.

---

## 5. Validation — every step

### 5.1 QSAR model validation (per target, done once at training time, on a GPU machine — not part of the desktop app's own runtime, but its output is what the app serves and displays)

Recorded per target in `run_metadata.json` (downloadable from the Target Info tab) and rendered as 9 standard plots:

- **Train/test split**: 85/15, held out honestly, `random_state=42` for reproducibility. Scaffold count is also recorded (e.g. 2,589 distinct Murcko scaffolds across 6,543 compounds for BRD4) so the split's chemical diversity is auditable.
- **Headline metrics**: R², Q², RMSE, MAE, Pearson r, bias, SDEP — all on the **held-out test set**, never training-set numbers.
- **Tropsha acceptability criteria** — the standard QSAR external-validation test, all three conditions recorded explicitly per target:
  - R² > 0.6
  - (R² − R₀²)/R² < 0.1
  - 0.85 ≤ k ≤ 1.15 (regression slope through origin)
- **Y-randomisation** (`Y_Random_DeltaR2`): the target variable is shuffled and the model retrained; a large drop in R² versus the real-label model (recorded, e.g. Δ 0.98 for BRD4) demonstrates the real model isn't just fitting noise/chance correlation.
- **Applicability-domain coverage** (`AD_Coverage_pct`): what fraction of the held-out test set itself falls inside the model's own training domain, at the same z-score gate the live app uses (§4.3).
- **Chemprop-alone comparison** (`Chemprop_Alone_R2`): quantifies the actual benefit of the two-stage architecture over the graph model alone (§4.1).

Every one of these numbers, plus the full package-version environment (Python, RDKit, PyTorch, Chemprop, AutoGluon, CUDA/GPU used) the model was trained under, is stored per target and downloadable — nothing here is asserted without a file backing it.

### 5.2 Automated software test suite (`tests/`, pytest)

**39 tests across 6 files**, run against real model buckets and the real FastAPI app (not mocks), specifically targeting the correctness traps the codebase's own documentation calls out:

| File | Tests | What it proves |
|---|---|---|
| `test_app_api.py` | 10 | End-to-end: health check, target listing, predict (in-domain and unparsable SMILES), ADMET worker-down graceful fallback, docking status display, the full Screen pipeline, and the factory browser's **path-traversal guard** (a real security check) |
| `test_featurize.py` | 7 | SMILES standardisation; that `self_check()` genuinely catches a naming/version drift instead of silently zero-filling (§4.2) |
| `test_model_adapter.py` | 6 | Unknown-target raises a clean `BucketError` (not a crash); feature-width parity; a **real bug the test suite caught**: an extreme out-of-distribution SMILES (a long repeating-unit chain) produced a value that was finite in float64 but overflowed float32 once AutoGluon's sklearn child models cast to it, crashing `sklearn.check_array` — fixed by clipping to a safe finite range before prediction (visible today as the `.clip(-1e6, 1e6)` in `Target.predict()`) |
| `test_applicability.py` | 6 | A deliberately-constructed extreme feature vector is correctly flagged out-of-domain (a synthetic vector is used rather than searching for a "weird" real molecule, since this target's AD averages over 2,310 mostly-binary features and a few extreme continuous descriptors can wash out below threshold on a real molecule — verified empirically, documented in the test itself) |
| `test_confidence.py` | 4 | Out-of-domain → `out` tier; unknown RMSE → `med`, explicitly labelled "unknown" rather than fabricated |
| `test_docking_units.py` | 6 | GNINA absent → confidence correctly capped at `medium`; PoseBusters present but Vina absent → availability reports **partial** readiness instead of crashing; the distance-based interaction fallback works without PLIP |

### 5.3 Docking validation methodology (per target, before a receptor is trusted)

Documented in `docking/README.md` as the required workflow before any target's `validated` flag may be set to `true`:

1. **Receptor preparation** (`receptor_prep.prepare_receptor`) — writes a profile to `docking_registry.json` with `validated: false` by default.
2. **Reference redocking** (`pipeline.redock_reference`) — re-dock the target's own known co-crystallised ligand into the prepared receptor and measure the atom-map-safe RMSD (§4.6) between the redocked pose and the real crystal pose. **< ~2.0 Å is the pass/fail threshold.** This proves the receptor geometry and search box are physically sound — it is the primary, hard gate.
3. **Enrichment test** (`scripts/enrichment_test.py`) — dock a set of known actives and decoys and check whether actives rank above decoys (ROC-AUC, Enrichment Factor at top 20%). This is recorded for transparency **but does not gate** the `validated` flag: weak ranking on a handful of compounds doesn't prove the geometry is wrong, and strong ranking doesn't substitute for the RMSD proof.
4. Only once step 2 passes does `validated: true` get written, together with the real `reference_rmsd`, `enrichment_auc`, and `enrichment_ef20` numbers. The UI shows a VALIDATED/UNVALIDATED badge with these real numbers; the Screen pipeline (§4.7 step 6) refuses to use docking for a target until it is validated.

**Decoy methodology — now a real DUD-E-style generator, not a proxy.** Originally, "decoys" for every target except `cox2` were that target's own weakest real measured ChEMBL binders (bottom-N by pChEMBL) — a real but methodologically weak comparison, since a "weak binder" for a target is still a molecule shaped for that target's pocket. This was replaced this session with `scripts/generate_decoys.py`, a proper two-part DUD-E-style (Mysinger et al. 2012) decoy generator that runs entirely offline:

1. **Property-matched** — a decoy must resemble a real active's molecular weight (±30 Da), LogP (±1.0), H-bond donors (±1), H-bond acceptors (±2), rotatable bonds (±2), and exact formal charge.
2. **Topologically dissimilar** — a decoy must have Morgan/ECFP4 Tanimoto similarity < 0.25 to *every* active, so it can't be a close 2D analog that would trivially dock well and defeat the purpose of the test.

The candidate pool is drawn from the ~100k+ real ChEMBL compounds curated for this project's *other* ~64 targets (excluding the target under test), since no internet-based decoy database (e.g. ZINC) is wired up — "presumed inactive" here honestly means "curated for a different target's assay, not this one," not independently confirmed non-binding. This is recorded verbatim per target in `enrichment_source`, and is a materially harder, more honest test than the old proxy (see the AUC drop for BRD4 below). The legacy weakest-binder method is kept as an explicit opt-in fallback (`--decoy-method weakest_binder`) for targets whose curated pool is too sparse for property-matching to find enough dissimilar decoys, but is no longer the default.

### 5.4 This session's docking validation campaign

Starting state: `docking_registry.json` had exactly **2 of 52** targets with any receptor at all (`cox2`, a non-QSAR reference target with a hand-curated true-decoy enrichment set; and `CHEMBL1862_ABL1`), and the `docking_targets/` directory holding the actual prepared receptor files was **entirely absent** from this machine — so even those 2 could not dock.

**Infrastructure stood up** (isolated from the host's nearly-full root disk, 6.9 GB free of 551 GB, on `/home/storage` instead): AutoDock Vina binary; a Python venv with Meeko, PDBFixer/OpenMM, PoseBusters, Biopython, gemmi, scikit-learn.

**Automated per-target tooling built** (new, reusable, not one-off scripts):
- `scripts/select_receptor.py` — gene symbol → UniProt accession → real PDB structures (via UniProt's own cross-reference list, filtered by resolution and X-ray method) → the best real drug-like bound ligand per candidate structure, with an extensive exclusion blacklist for crystallization additives, cryoprotectants, N-/O-glycosylation sugars, and non-hydrolyzable ATP/GTP nucleotide analogs (all of which showed up as false-positive "ligand" picks during this session and were fixed).
- `scripts/detect_chain.py` — auto-picks which protein chain actually carries the reference ligand (see the duplicate-ligand bug below).
- `scripts/pdb_fetch.py` — falls back to mmCIF + `gemmi` conversion when RCSB has no legacy `.pdb` file for a newer structure (increasingly common for recent depositions).
- `scripts/generate_decoys.py` — real DUD-E-style decoy generation (property-matched + topologically-dissimilar, from other targets' curated ChEMBL data), replacing the earlier weakest-own-binder proxy — see §5.3's decoy-methodology note.
- `scripts/batch_validate.py` — drives the existing `scripts/validate_target.py` per target as an **isolated subprocess** (one target's crash or hang can't take the batch down), falls through to the next candidate PDB structure on failure, logs every attempt to `scripts/batch_validate_log.jsonl`, and **never writes a fabricated `validated` entry** — a target that exhausts every candidate is left honestly unresolved.

**Two real, previously-latent bugs were found and fixed in `docking/receptor_prep.py`** (these were blocking receptor preparation for essentially every target, not just the one first encountered on):

1. **C-terminal valence crash.** PDBFixer correctly completes every protein chain terminus with an `OXT` atom (standard carboxylate chemistry). Meeko's PDB→molecule bond-order guesser, which works from interatomic distance alone (no chemical templates at that stage), sees the terminal carbon's two near-equidistant C–O contacts (the backbone `O` and `OXT`) and incorrectly assigns **both** as double bonds, pushing that carbon's valence to 5 and crashing receptor preparation outright — on every chain terminus, in every target. **Fix**: strip the `OXT` atom after PDBFixer's repair step (Vina scores a rigid receptor purely from atom positions/types, not formal bond orders, so this costs nothing chemically relevant to docking).
2. **Duplicate-ligand RMSD corruption.** Many real PDB depositions contain 2+ copies of the same protein (and its bound ligand) in the crystallographic asymmetric unit — confirmed on `1IEP` (ABL1), which has the reference ligand in both chain A and chain B. Extracting the crystal ligand without a chain restriction pulled in **both** copies as one nonsensical two-fragment "molecule," which the atom-map-safety check in `docking/rmsd.py` correctly refused to compare (rather than silently returning a wrong number) — but this meant validation could never succeed. **Fix**: `scripts/detect_chain.py` restricts receptor prep and reference-ligand extraction to whichever single chain actually carries the ligand.

A third, structure-specific (not systemic) failure mode was also diagnosed and documented rather than "fixed" — an intermittent RDKit distance-based bond-order misperception on certain **arginine guanidinium groups** (a resonance-symmetric functional group, same underlying class of issue as #1 above, but occurring only for specific PDB structures' geometry, not universally). No newer `meeko` release exists to fix this upstream; the batch tooling's multi-candidate fallback already absorbs it (a different source structure for the same target typically succeeds), and error messages from `mk_prepare_receptor.py` were improved (the underlying RDKit sanitization error was previously swallowed by a bare subprocess exception) so any future occurrence is immediately diagnosable.

**Final results — full 52-target batch complete.** Every enrichment AUC/EF@20% below is from the real property-matched/topologically-dissimilar decoy generator (§4.6/§5.3), except `cox2` (its own separately-curated true-decoy set, pre-dating this session). Coverage: **36 of 52 QSAR targets (69%) + `cox2`** now have a geometrically-validated docking receptor, up from 2 of 52 at the start of this work.

*Validated (RMSD < 2.0 Å), sorted by target ID:*

| Target | RMSD (Å) | Enrichment AUC | EF@20% |
|---|---|---|---|
| `cox2` | 0.834 | 0.817 | 2.67 |
| `CHEMBL1163125_BRD4` | 1.292 | 0.336 | 0.6 |
| `CHEMBL1824_ERBB2` | 0.716 | 0.852 | 1.8 |
| `CHEMBL1844_CSF1R` | 1.822 | 0.621 | 1.8 |
| `CHEMBL1906_RAF1` | 0.565 | 0.683 | 1.73 |
| `CHEMBL1907611_p53_MDM2` | 0.773 | 0.516 | 1.2 |
| `CHEMBL1936_KIT` | 0.742 | 0.633 | 1.8 |
| `CHEMBL1937_HDAC2` | 0.737 | 0.759 | 1.97 |
| `CHEMBL1974_FLT3` | 0.981 | 0.820 | 2.4 |
| `CHEMBL1978_CYP19A1` | 0.133 | 0.438 | 0.6 |
| `CHEMBL2007625_IDH1` | 1.085 | 0.246 | 0.0 |
| `CHEMBL203_EGFR` | 1.536 | 0.359 | 0.6 |
| `CHEMBL2041_RET` | 0.870 | 0.555 | 0.6 |
| `CHEMBL2093865_HDAC_family` | 0.755 | 0.375 | 1.8 |
| `CHEMBL2093869_ITGA2B_ITGB3` | 1.816 | 0.449 | 0.6 |
| `CHEMBL2147_PIM1` | 0.249 | 0.430 | 0.6 |
| `CHEMBL2148_JAK3` | 0.976 | 0.348 | 0.6 |
| `CHEMBL220_AChE` | 0.315 | 0.789 | 1.2 |
| `CHEMBL268_CTSK` | 1.507 | 0.523 | 1.2 |
| `CHEMBL2742_FGFR3` | 1.069 | 0.629 | 0.6 |
| `CHEMBL279_KDR` | 1.973 | 0.570 | 1.2 |
| `CHEMBL280_MMP13` | 1.492 | 0.670 | 2.06 |
| `CHEMBL2820_F11` | 0.958 | 0.648 | 1.8 |
| `CHEMBL2835_JAK1` | 0.996 | 0.527 | 0.6 |
| `CHEMBL286_REN` | 1.387 | 0.404 | 0.58 |
| `CHEMBL2971_JAK2` | 1.259 | 0.168 | 0.0 |
| `CHEMBL3105_PARP1` | 1.719 | 0.984 | 3.0 |
| `CHEMBL3130_PIK3CD` | 0.289 | 0.289 | 0.0 |
| `CHEMBL3267_PIK3CG` | 1.069 | 0.453 | 1.2 |
| `CHEMBL333_MMP2` | 1.340 | 0.385 | 0.66 |
| `CHEMBL3553_TYK2` | 1.310 | 0.812 | 1.8 |
| `CHEMBL3717_MET` | 1.035 | 0.859 | 3.0 |
| `CHEMBL3880_HSP90AA1` | 0.212 | 0.355 | 0.0 |
| `CHEMBL4282_AKT1` | 1.708 | 0.113 | 0.0 |
| `CHEMBL4439_TGFBR1` | 0.128 | 0.543 | 1.2 |
| `CHEMBL5145_BRAF` | 1.029 | 0.500 | 1.2 |

*Unvalidated — receptor prepped, redocked, but RMSD stayed above the 2.0 Å threshold across every automated candidate tried (real result, not a failure to run):*

| Target | Best RMSD (Å) achieved |
|---|---|
| `CHEMBL1862_ABL1` | 3.028 |
| `CHEMBL1951_MAOA` | — (crystal-ligand template mismatch on both candidates tried; RMSD could not be computed, not fabricated) |
| `CHEMBL1957_IGF1R` | 2.055 |
| `CHEMBL215_ALOX5` | 2.251 |
| `CHEMBL235_PPARG` | — (template mismatch) |
| `CHEMBL248_ELANE` | 2.011 |
| `CHEMBL2581_CTSD` | 3.293 |
| `CHEMBL258_LCK` | 2.634 |
| `CHEMBL2842_MTOR` | 6.635 |
| `CHEMBL3572_CETP` | 4.560 |
| `CHEMBL3973_FGFR4` | 2.897 |

*No registry entry at all — every automated candidate either had no usable ligand, or failed receptor preparation outright (structure-specific data quirks, e.g. missing residues creating chain breaks meeko's capping logic can't resolve):*

`CHEMBL1907601_CDK4_CyclinD1` (multi-subunit complex — genuinely harder to prep automatically), `CHEMBL1913_PDGFRB`, `CHEMBL1991_IKBKB`, `CHEMBL262_GSK3B`, `CHEMBL3650_FGFR1`, `CHEMBL4142_FGFR2`.

**What the real-decoy numbers actually show, across all 36 validated targets:** enrichment quality varies genuinely and substantially by target — from `PARP1` (0.984) and `MET` (0.859), both near-perfect separation of real actives from true decoys, down to `AKT1` (0.113) and `JAK2` (0.168), both *worse than random*, meaning Vina's raw score actively anti-ranks real binders for those two receptors. The mean AUC across all 36 targets is ≈0.54 — barely above the 0.5 no-signal baseline — which is an important, honest headline finding: **geometric validity (RMSD) and ranking usefulness (enrichment) are largely independent properties of a docking receptor.** A target can reproduce its crystal pose almost perfectly (e.g. `TGFBR1` at 0.128 Å) while its docking *score* still doesn't reliably separate potent from weak binders (`TGFBR1`'s AUC is 0.543, barely above chance). This is exactly why `enrichment_auc` is recorded but never used to gate the `validated` flag (§5.3) — it's diagnostic information for how much to trust Vina's *ranking* on a given target, layered on top of (never a substitute for) the RMSD proof that the pose geometry itself is correct. In practice: for roughly half of the 36 validated targets, the Screen pipeline's docking contribution to the fused rank score (§4.7, weighted 35%) should be read with real skepticism, target by target, using the table above — not assumed uniformly trustworthy just because `validated: true`.

An important, explicitly-preserved honesty point from this session: Vina's global search is **not seeded**, so the same receptor can give a different redock RMSD on different runs (observed directly: `CHEMBL1862_ABL1` scored 1.425 Å in an earlier/different run recorded historically in the registry, and 3.028 Å in this session's rerun of the identical receptor). Rather than raising Vina's search effort (`exhaustiveness`) specifically for the validation step to force more passes, the same setting used in live serving was kept for validation — because the point of validation is to prove what a real user's screening run will actually achieve, not a best-case number.

---

## 6. Data & model inventory

- **`models/` — 52 usable QSAR target buckets**, each containing: the trained AutoGluon predictor + Chemprop checkpoint (`chosen_model/`, `_cache/`), the exact ordered feature list (`selected_features.csv`), training/test data (`Data/`), the 9 diagnostic plots (`Plots/`), and full run metadata/metrics. Total on-disk size ≈ 101 GB (intentionally **not** committed to git — see `.gitignore` — treated as large, read-only build output, not source code).
- **13 additional targets have curated training data but no usable model** — training crashed with `Input X contains infinity or a value too large for dtype('float32')` (an unsanitized-infinite-descriptor bug in the upstream training pipeline, outside this repo): `CHEMBL2000_KLKB1`, `CHEMBL2034_NR3C1`, `CHEMBL206_ESR1`, `CHEMBL2189121_KRAS`, `CHEMBL2599_SYK`, `CHEMBL267_SRC`, `CHEMBL2815_NTRK1`, `CHEMBL3706_ADAM17`, `CHEMBL4005_PIK3CA`, `CHEMBL4040_MAPK1`, `CHEMBL4860_BCL2`, `CHEMBL6136_KDM1A`. Several are high-value oncology targets (ESR1, KRAS, SRC, PIK3CA, BCL2) that are consequently silently absent from the app.
- **`models/curated/`** — 64 CSVs of curated ChEMBL activity data (input to training, including for the 13 failed targets above).
- **`docking_targets/` + `docking_registry.json`** — prepared, geometrically-validated receptors for structure-based docking (§5.4); **36 of 52 QSAR targets (69%) validated** as of this document, plus the standalone `cox2` reference target. The full 52-target automated batch has completed; 11 targets did not pass the RMSD gate and 6 have no usable automated receptor at all (§5.4).

---

## 7. Limitations

Stated as plainly as the codebase itself states them — this list is deliberately not softened:

1. **Docking coverage is 36 of 52 QSAR targets (69%), not all of them.** The full automated batch has run to completion (plus `cox2`); 11 targets were attempted but never passed the RMSD reproducibility gate, and 6 have no usable automated receptor at all (either no viable PDB/ligand candidate was found, or receptor preparation failed on every candidate tried — usually a structure-specific data quirk like a chain break). The Screen pipeline degrades gracefully (QSAR-only) for any unvalidated target — it never fabricates a docking result. A domain expert manually curating a PDB structure for the 17 remaining/failed targets (rather than the automated resolution-ranked search) would likely recover some of them, particularly the 6 with zero automated candidates.
2. **Enrichment AUC is weakly correlated with RMSD validity, and often close to random.** Across the 36 validated (geometrically correct) receptors, mean enrichment AUC is only ≈0.54 — several targets with excellent redocking RMSD (e.g. `TGFBR1` at 0.128 Å) still show near-chance ranking ability (AUC 0.543). A `validated: true` badge means the receptor geometry and search box are correct; it does **not** mean Vina's score reliably ranks compounds for that target — see the full table in §5.4 before trusting docking-influenced rankings for any specific target.
3. **13 targets have no QSAR model at all** due to an upstream training-data-cleaning bug (infinite/overflow descriptor values), not something fixable from this application.
4. **No genuine per-compound prediction interval.** The shipped AutoGluon models are a single fit/test split; the "confidence tier" is honestly built from applicability-domain status + the target's own held-out test RMSE, not a calibrated conformal interval. This is a deliberately more modest claim, stated explicitly in the UI.
5. **Docking "decoys" are real molecules but not independently confirmed non-binders.** `scripts/generate_decoys.py` now generates genuine DUD-E-style property-matched, topologically-dissimilar decoys (replacing the earlier weakest-own-binder proxy), but its candidate pool is other targets' curated ChEMBL compounds, not a true "presumed inactive" database like ZINC — "presumed inactive" here means "curated for a different target's assay," which is a real, disclosed, and now a genuinely harder methodological choice than the original proxy, but still not identical to a validated DUD-E/ZINC benchmark.
6. **Docking confidence is capped at `medium` without GNINA.** GNINA (a CNN second-opinion rescorer) is optional and was not installed in this session's environment; this is documented in the codebase as an intentional cap, not a bug.
7. **Vina's search is not seeded**, so redocking RMSD (and thus which targets validate) has genuine run-to-run variance for structures near the 2.0 Å threshold — confirmed directly this session (e.g. `CHEMBL1862_ABL1`'s same receptor scored 1.425 Å, 3.028 Å, and 3.028 Å again across different runs). A "not validated" result for a borderline target is not necessarily a permanent verdict.
8. **PLIP (gold-standard interaction typing) could not be installed** in this session's environment (its build script's own pinned OpenBabel dependency failed to compile from source); the app automatically falls back to a built-in distance-based interaction detector, which is coarser (H-bond/hydrophobic only, no atom-level identity) and is labelled "(distance-based)" everywhere it's shown so it never overstates its precision.
9. **ADMET's learned layer (ADMET-AI) is optional** and must be started as a separate worker process; if it isn't running, the app still functions with the always-on deterministic rule-based layer only, with a clear notice.
10. **Automated receptor/ligand selection is not infallible.** `scripts/select_receptor.py`'s heuristics (resolution, molecular weight, an additive/glycan/nucleotide-analog exclusion blacklist) are good defaults but not a substitute for a domain expert's structure choice — several false positives (a glycosylation sugar, non-hydrolyzable nucleotide analogs) were caught and fixed during this session precisely because this is heuristic, not guaranteed-correct, selection; the 6 targets with zero automated candidates and several of the 11 unvalidated ones are the direct cost of that heuristic ceiling.
11. **This machine's root filesystem was at 99% capacity** (6.9 GB free) throughout this work; all new tooling, dependencies, and temporary files were deliberately isolated to a separate, larger volume to avoid risking the host system — worth resolving independently of this application.
12. **Docking validation was run serially, single-target-at-a-time**, with no parallelization — the full 52-target batch took multiple hours of real Vina compute. Re-running it (e.g. after further tuning the receptor-selection heuristics) is a multi-hour undertaking each time, not a quick batch job.

---

## 8. Deployment

- **Development**: `python desktop.py` — starts the FastAPI backend on a free local port and opens it in a native PyWebview window; falls back to printing a plain browser URL if no native GUI backend is available on the machine.
- **Optional ADMET-AI worker**: `uvicorn admet_service:app --host 127.0.0.1 --port 8100`, started separately.
- **Windows `.exe` build**: PyInstaller (`pyinstaller --windowed --name PhytoScreen ...`, full flags in `BUILD_WINDOWS.md`), bundling `static/`, `docking/`, `docking_registry.json`, and `--collect-all` for RDKit/AutoGluon/Chemprop/Lightning/PoseBusters/Meeko/gemmi plus hidden imports for LightGBM etc.

---

## 9. Appendix — file/module map

```
app.py                    FastAPI backend, all REST endpoints
desktop.py                native-window launcher
analysis.py                multi-target / Compare analysis
admet.py / admet_endpoints.py / admet_service.py    ADMET (deterministic + learned worker)
factory_browser.py        /api/factory/* — Target Info tab
serving/
  model_adapter.py          bucket loading, two-stage inference, LRU cache
  featurize.py               SMILES -> training feature space + self-check
  applicability.py           AD z-score gate
  confidence.py              honest confidence tiers
  screen.py                  the 8-step Screen pipeline
docking/
  receptor_prep.py           one-time receptor prep (this session's bug fixes live here)
  ligand_prep.py              SMILES -> 3D -> PDBQT
  engines.py                  VinaEngine, GninaRescorer
  validity.py                 PoseBusters gate
  consensus.py                 pose selection + confidence
  rmsd.py                      atom-map-safe RMSD
  profile.py                   registry load/save, portable receptor paths
  pipeline.py                  dock_compound (per-compound), redock_reference (validation)
  interactions.py / interaction_diagram.py    interaction detection + 2D diagram rendering
  availability.py               reports which docking tools/binaries are present
scripts/
  validate_target.py           generic per-target docking validation (existing)
  enrichment_test.py            AUC / EF@20% enrichment metrics (existing)
  select_receptor.py            NEW — automated PDB/ligand candidate selection
  detect_chain.py                NEW — auto chain detection (duplicate-ligand fix)
  pdb_fetch.py                   NEW — mmCIF fallback fetch
  generate_decoys.py             NEW — real DUD-E-style decoy generation
  batch_validate.py              NEW — orchestrates validate_target.py across all targets
static/index.html          entire frontend (six tabs, vanilla JS)
models/<target_id>/         per-target QSAR training bucket (read-only, not in git)
docking_targets/<target_id>/  prepared receptors (read-only, not in git)
docking_registry.json       docking target registry + validation record
tests/                       39 pytest tests across 6 files (§5.2)
```
