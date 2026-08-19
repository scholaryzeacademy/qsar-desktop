"""
============================================================
  PhytoScreen — Desktop serving backend (app.py)
============================================================
  Prediction-first serving app. NO training here (CLAUDE.md §1). Loads
  the real target buckets in models/<target_id>/ (AutoGluon + Chemprop,
  see serving/model_adapter.py) — the app never touches a registry.json
  or raw pickle asset.

  One chosen model per target — no multi-model comparison UI (CLAUDE.md
  §13 guardrail).

  Run:
      uvicorn app:app --host 127.0.0.1 --port 8000
      open http://localhost:8000/

  Tabs served by one single-page UI: Predict / ADMET / Compare / Docking
  / Screen / Target Info.
============================================================
"""
import os
import warnings
warnings.filterwarnings("ignore")

import pandas as pd
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field
from typing import Optional, List

from serving import model_adapter as MA
import analysis as A
import admet as ADMET
import factory_browser

app = FastAPI(title="PhytoScreen", version="3.0")
app.include_router(factory_browser.router)

# The UI (frontend/) is a separate app/process — dev server (Vite) or a
# built static bundle served by anything, no longer served by this backend
# (see the removed desktop.py / static-mount). No cookies or session auth
# exist here, so a permissive default is safe; ALLOWED_ORIGINS lets a real
# deployment lock it down to its actual frontend origin(s).
_allowed_origins = [o.strip() for o in os.environ.get("ALLOWED_ORIGINS", "*").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

DISCLAIMER = ("Prioritisation aid, not a substitute for assays. Trust predictions only for "
              "in-domain molecules; treat the top of the list as a shortlist.")


def _num(v):
    try:
        if v is None or pd.isna(v):
            return None
        return round(float(v), 3)
    except Exception:
        return None


def _rows(df):
    """One dict per row. Out-of-domain rows NEVER carry a potency number —
       AD gating is enforced here, not just in the UI (CLAUDE.md §2)."""
    out = []
    for _, r in df.iterrows():
        in_ad = bool(r["In_AD"])
        out.append({
            "input_smiles": r.get("Input_SMILES"),
            "smiles": r.get("Standardised_SMILES"),
            "parsed_ok": bool(r.get("Parsed_OK")),
            "predicted_pIC50": _num(r.get("Predicted_pIC50")) if in_ad else None,
            "in_domain": in_ad,
            "ad_z": _num(r.get("AD_z")),
            "confidence": r.get("Confidence"),
            "confidence_label": r.get("Confidence_Label"),
            "confidence_basis": r.get("Confidence_Basis"),
        })
    return out


def _predict(target_id, smiles):
    if not smiles:
        raise HTTPException(400, "No SMILES provided.")
    try:
        target = MA.load_target(target_id)
    except MA.BucketError as e:
        raise HTTPException(409, str(e))
    except KeyError:
        raise HTTPException(404, f"Unknown target '{target_id}'")

    df = target.predict_smiles(smiles)
    unparsed = df[~df["Parsed_OK"]]
    parsed = df[df["Parsed_OK"]]
    in_dom = parsed[parsed["In_AD"]].sort_values("Predicted_pIC50", ascending=False).reset_index(drop=True)
    in_dom.insert(0, "Rank", range(1, len(in_dom) + 1))
    out_dom = parsed[~parsed["In_AD"]].reset_index(drop=True)

    in_rows = _rows(in_dom)
    for i, row in enumerate(in_rows):
        row["rank"] = i + 1

    return {
        "target": {"id": target.target_id, "name": target.name},
        "model": target.metrics.get("Best_Model") or target.metrics.get("best_model"),
        "model_metrics": {
            "test_r2": target.metrics.get("R2_Test"),
            "test_rmse": target.metrics.get("RMSE_Test"),
            "pearson_r": target.metrics.get("Pearson_r"),
            "ad_coverage_pct": target.metrics.get("AD_Coverage_pct"),
            "tropsha_pass": target.metrics.get("Tropsha_Pass"),
            "y_random_delta_r2": target.metrics.get("Y_Random_DeltaR2"),
        },
        "counts": {"in_domain": int(len(in_dom)), "out_of_domain": int(len(out_dom)),
                   "skipped": int(len(unparsed)), "submitted": int(len(smiles))},
        "in_domain": in_rows,
        "out_of_domain": _rows(out_dom),
        "skipped": [str(s) for s in unparsed["Input_SMILES"].tolist()],
        "ranked_by": "predicted_pIC50",
        "disclaimer": DISCLAIMER,
    }


# ---------------- models ----------------
class PredictBody(BaseModel):
    target_id: str
    smiles: List[str]


class MultiBody(BaseModel):
    smiles: List[str]
    target_ids: Optional[List[str]] = None


@app.get("/api/health")
def health():
    ids = MA.list_target_ids()
    try:
        dock_ready = bool(DOCK_AVAIL and DOCK_AVAIL.status()["ready"])
    except Exception:
        dock_ready = False
    return {"targets_in_bucket_dir": len(ids), "targets_dir": MA.TARGETS_DIR,
            "admet_ai": ADMET.learned_status()["available"],
            "docking": "ready" if dock_ready else "not_ready", "disclaimer": DISCLAIMER}


@app.get("/api/targets")
def targets():
    out = []
    for meta in MA.list_targets_meta():
        m = meta["metrics"]
        out.append({"target_id": meta["target_id"], "name": meta["target_id"],
                    "best_model": m.get("Best_Model") or m.get("best_model"),
                    "n_compounds": m.get("Total_N") or (m.get("counts") or {}).get("total"),
                    "test_r2": m.get("R2_Test"), "test_rmse": m.get("RMSE_Test"),
                    "ad_coverage_pct": m.get("AD_Coverage_pct"), "tropsha_pass": m.get("Tropsha_Pass")})
    out.sort(key=lambda x: x["target_id"])
    return {"targets": out}


@app.post("/api/predict")
def predict(body: PredictBody):
    return _predict(body.target_id, [s.strip() for s in body.smiles if s and s.strip()])


@app.post("/api/predict_csv")
async def predict_csv(target_id: str = Form(...), file: UploadFile = File(...)):
    import io
    df = pd.read_csv(io.BytesIO(await file.read()))
    col = "SMILES" if "SMILES" in df.columns else ("smiles" if "smiles" in df.columns else df.columns[0])
    smiles = [str(s).strip() for s in df[col].dropna().tolist() if str(s).strip()]
    return _predict(target_id, smiles)


@app.post("/api/parse_sdf")
async def parse_sdf(file: UploadFile = File(...)):
    """SDF -> SMILES list, for the SDF input mode on every input tab (Screen/
       Predict/ADMET/Compare/Docking) — RDKit is far more reliable at reading
       an SDF's bond/stereo perception server-side than any client-side JS
       parser would be, so every tab funnels SDF uploads through here and
       then treats the result exactly like a pasted SMILES list."""
    import io
    from rdkit import Chem
    data = await file.read()
    if not data:
        raise HTTPException(400, "Empty file.")
    suppl = Chem.ForwardSDMolSupplier(io.BytesIO(data), removeHs=False, sanitize=True)
    smiles, names, n_skipped = [], [], 0
    for mol in suppl:
        if mol is None:
            n_skipped += 1
            continue
        try:
            smiles.append(Chem.MolToSmiles(mol))
        except Exception:
            n_skipped += 1
            continue
        names.append(mol.GetProp("_Name") if mol.HasProp("_Name") else None)
    if not smiles:
        raise HTTPException(400, "No parsable molecules found in this SDF file.")
    return {"smiles": smiles, "names": names, "n_parsed": len(smiles), "n_skipped": n_skipped}


@app.post("/api/predict_multi")
def predict_multi(body: MultiBody):
    smiles = [s.strip() for s in body.smiles if s and s.strip()]
    if not smiles:
        raise HTTPException(400, "No SMILES provided.")
    if not body.target_ids:
        raise HTTPException(400, "Provide target_ids.")
    target_ids = body.target_ids
    result = A.analyse(smiles, target_ids)
    if not result["targets"]:
        raise HTTPException(409, f"No usable targets among {target_ids}.")
    return result


ADMET_SYNC_MAX = 50          # lists this size or smaller run synchronously
_ADMET_JOBS = {}             # main-app job store: id -> {det, worker_job, ...}


@app.post("/api/admet")
def admet(body: PredictBody):
    import uuid
    smiles = [s.strip() for s in body.smiles if s and s.strip()]
    if not smiles:
        raise HTTPException(400, "No SMILES provided.")
    det = ADMET.deterministic_profiles(smiles)
    status = ADMET.learned_status()
    std = [p["standardised_smiles"] for p in det if p.get("parsed_ok")]

    # no worker, or nothing valid -> deterministic only, immediately
    if not status["available"] or not std:
        for p in det:
            p["learned"] = {"available": False, "note": status.get("note")}
        return {"mode": "result", "profiles": det, "learned": status, "disclaimer": DISCLAIMER}

    # small -> synchronous
    if len(std) <= ADMET_SYNC_MAX:
        preds = ADMET.worker_profile(std)
        if preds is None:
            for p in det:
                p["learned"] = {"available": False, "note": "ADMET-AI worker did not respond."}
        else:
            ADMET.attach_learned(det, preds)
        return {"mode": "result", "profiles": det, "learned": status, "disclaimer": DISCLAIMER}

    # large -> async job (isolated worker), UI polls
    wj = ADMET.worker_submit(std)
    if wj is None:
        for p in det:
            p["learned"] = {"available": False, "note": "ADMET-AI worker did not accept the job."}
        return {"mode": "result", "profiles": det, "learned": status, "disclaimer": DISCLAIMER}
    jid = uuid.uuid4().hex[:12]
    _ADMET_JOBS[jid] = {"det": det, "worker_job": wj}
    return {"mode": "job", "job_id": jid, "total": len(std), "disclaimer": DISCLAIMER}


@app.get("/api/admet/job/{jid}")
def admet_job(jid: str):
    job = _ADMET_JOBS.get(jid)
    if not job:
        raise HTTPException(404, "unknown job")
    st = ADMET.worker_poll(job["worker_job"])
    if st is None:
        raise HTTPException(502, "ADMET-AI worker unreachable")
    if st["status"] == "done":
        ADMET.attach_learned(job["det"], st.get("predictions") or {})
        _ADMET_JOBS.pop(jid, None)
        return {"status": "done", "profiles": job["det"], "learned": {"available": True, "source": "ADMET-AI"},
                "disclaimer": DISCLAIMER}
    if st["status"] == "error":
        _ADMET_JOBS.pop(jid, None)
        return {"status": "error", "error": st.get("error")}
    return {"status": st["status"], "done": st.get("done", 0), "total": st.get("total", 0)}


# ---------------- docking (availability-gated) ----------------
try:
    from docking import availability as DOCK_AVAIL
    from docking import pipeline as DOCK_PIPE
    from docking import profile as DOCK_PROFILE
    from docking import recommend as DOCK_RECOMMEND
    _DOCK_IMPORT_ERR = None
except Exception as e:
    DOCK_AVAIL = DOCK_PIPE = DOCK_PROFILE = DOCK_RECOMMEND = None
    _DOCK_IMPORT_ERR = str(e)

_DOCK_JOBS = {}


@app.get("/api/docking/status")
def docking_status():
    if DOCK_AVAIL is None:
        return {"ready": False, "import_error": _DOCK_IMPORT_ERR,
                "note": "Docking package not importable — install its dependencies (rdkit, meeko, posebusters)."}
    st = DOCK_AVAIL.status()
    st["planned"] = ["AutoDock Vina docking + PoseBusters physical-validity gate",
                     "GNINA CNN rescoring (second opinion, optional)",
                     "2D protein-ligand interaction diagram",
                     "Per-target reference-redocking + enrichment validation"]
    try:
        reg = DOCK_PROFILE.load_registry()
        st["docking_targets"] = [t for t, r in reg.items() if r.get("validated")]
        st["target_details"] = [{
            "target_id": t, "name": r.get("name", t),
            "validated": bool(r.get("validated")),
            "reference_rmsd": r.get("reference_rmsd"),
            "enrichment_auc": r.get("enrichment_auc"),
            "enrichment_ef20": r.get("enrichment_ef20"),
            "enrichment_n": r.get("enrichment_n"),
            "site_source": r.get("site_source"),
        } for t, r in reg.items()]
    except Exception:
        st["docking_targets"] = []
        st["target_details"] = []
    return st


@app.get("/api/docking/targets")
def docking_targets():
    if DOCK_PROFILE is None:
        return {"targets": []}
    reg = DOCK_PROFILE.load_registry()
    return {"targets": [{"target_id": t, "name": r.get("name", t)}
                        for t, r in reg.items() if r.get("validated")]}


@app.get("/api/diseases")
def diseases():
    """Diseases (from panel_results_v2.csv) that have >=1 associated target
       among our QSAR-modeled targets — most of the CSV's diseases fall
       away here since it covers ~669 genes and we only model ~52."""
    if DOCK_RECOMMEND is None:
        return {"diseases": []}
    return {"diseases": DOCK_RECOMMEND.list_diseases()}


@app.get("/api/diseases/{disease_id}/targets")
def disease_targets(disease_id: str):
    """Our targets associated with disease_id, ranked by disease-association
       score, annotated with real docking-validation status and QSAR
       quality — nothing here is invented."""
    if DOCK_RECOMMEND is None:
        return {"targets": []}
    return {"targets": DOCK_RECOMMEND.targets_for_disease(disease_id)}


@app.get("/api/targets/{target_id}/recommendation")
def target_recommendation(target_id: str):
    """The 'Why this?' evidence bundle for one target's recommended docking
       structure: our own empirical validation plus panel_results_v2.csv's
       crystallographic context."""
    if DOCK_RECOMMEND is None:
        raise HTTPException(503, "Docking package not available")
    rec = DOCK_RECOMMEND.recommendation(target_id)
    if rec is None:
        raise HTTPException(404, f"'{target_id}' is not one of our QSAR-modeled targets")
    return rec


@app.get("/api/docking/receptor/{target_id}")
def docking_receptor(target_id: str):
    """Raw receptor PDB text, for the 3D pose viewer (protein context around
       the docked ligand). Same file docking already uses for PoseBusters/PLIP."""
    if DOCK_PROFILE is None:
        raise HTTPException(503, "Docking package not available")
    profile = DOCK_PROFILE.load_profile(target_id)
    receptor_pdb = profile.get("receptor_pdb")
    if not receptor_pdb or not os.path.exists(receptor_pdb):
        raise HTTPException(404, f"no receptor PDB for '{target_id}'")
    return PlainTextResponse(open(receptor_pdb).read())


@app.get("/api/docking/receptor_file")
def docking_receptor_file(path: str):
    """Serves a receptor PDB by its own file path rather than by target_id —
       used for the binding-site 3D preview and the dock-results pose viewer
       whenever the receptor in play isn't (or might not be) the registry's
       automatic default: an Advanced Settings custom structure (any
       target, not just no-QSAR-model ones — its receptor_pdb is an
       absolute path already known client-side from the custom-receptor
       job's response, not a registry target_id) or the exact receptor a
       completed docking job actually used. Restricted to docking_targets/
       — never an arbitrary filesystem path — so this can't be used to read
       anything else on the box."""
    allowed_root = os.path.abspath("docking_targets")
    real = os.path.abspath(path)
    if not (real == allowed_root or real.startswith(allowed_root + os.sep)) or not os.path.exists(real):
        raise HTTPException(403, "path not allowed")
    return PlainTextResponse(open(real).read())


def _structure_candidates_for_gene(gene, default_pdb=None):
    """Shared by both structure_candidates() (QSAR-modeled targets) and
       gene_structure_candidates() (any protein in the Version 2 CSV, model
       or not) — everything here only needs a gene symbol, never a real
       QSAR target_id."""
    from scripts import panel_candidates as PC
    df = PC._panel_df()
    if df is None or gene not in df.index:
        return {"gene": gene, "default_pdb_id": default_pdb, "candidates": [], "n_qualifying_structures": 0}
    row = df.loc[gene]
    ranked_ids = [p for p in str(row.get("all_pdb_ids_ranked") or "").split(";") if p]
    cands = PC._parse_top5(row.get("top5_pdb_summary"))
    import re as _re
    quality_re = _re.compile(r"^(\S+)\s+\(res=([\d.]+),\s*RSCC=([\d.]+),\s*RSR=([\d.]+)\)")
    quality_by_pdb = {}
    for chunk in str(row.get("top5_pdb_summary") or "").split(" | "):
        m = quality_re.match(chunk.strip())
        if m:
            quality_by_pdb[m.group(1)] = {"resolution": float(m.group(2)), "ligand_RSCC": float(m.group(3)),
                                          "ligand_RSR": float(m.group(4))}
    out = []
    for c in cands:
        try:
            rank = ranked_ids.index(c["pdb_id"]) + 1
        except ValueError:
            rank = None
        q = quality_by_pdb.get(c["pdb_id"], {})
        out.append({"pdb_id": c["pdb_id"], "resname": c["resname"], "csv_rank": rank,
                    "is_current_default": c["pdb_id"] == default_pdb,
                    "resolution": q.get("resolution"), "ligand_RSCC": q.get("ligand_RSCC"),
                    "ligand_RSR": q.get("ligand_RSR")})
    return {"gene": gene, "default_pdb_id": default_pdb, "candidates": out,
           "n_qualifying_structures": row.get("n_qualifying_structures"),
           "note": "Crystallographic quality ranking only — picking one here does NOT redock/validate it; "
                   "Vina's pose geometry for a manually-picked structure is unconfirmed until proven."}


@app.get("/api/targets/{target_id}/structure_candidates")
def structure_candidates(target_id: str):
    """Every qualifying structure for this target's gene from the Version 2
       CSV (panel_results_v2.csv), for Advanced Settings' manual structure
       picker — resolution/RSCC/RSR/ligand per candidate, plus which one is
       the current automatic default, so 'View Evidence' works per-row, not
       just for the top pick."""
    if DOCK_RECOMMEND is None:
        raise HTTPException(503, "Docking package not available")
    t2g, _ = DOCK_RECOMMEND._target_gene_map()
    gene = t2g.get(target_id)
    if gene is None:
        raise HTTPException(404, f"'{target_id}' is not one of our QSAR-modeled targets")
    default_pdb = None
    reg = DOCK_PROFILE.load_registry()
    src = (reg.get(target_id) or {}).get("pdb_source")
    if src:
        default_pdb = src.split("_raw")[0].split(".")[0].upper()
    return {"target_id": target_id, **_structure_candidates_for_gene(gene, default_pdb)}


@app.get("/api/genes/{gene_symbol}/structure_candidates")
def gene_structure_candidates(gene_symbol: str):
    """Same as structure_candidates(), but for ANY protein in the Version 2
       CSV — including the ~620 genes that have disease association evidence
       but no trained QSAR model. Powers 'docking only, no QSAR model'
       targets: the Screen tab's disease->target list no longer hides these,
       it routes them here instead so a receptor can still be built and
       docked against on demand (see /api/docking/receptor/custom, which
       already accepts any string as target_id — a QSAR model was never a
       structural requirement for it, only a UI convention)."""
    if DOCK_RECOMMEND is None:
        raise HTTPException(503, "Docking package not available")
    default_pdb = None
    reg = DOCK_PROFILE.load_registry()
    src = (reg.get(f"GENE_{gene_symbol.upper()}") or {}).get("pdb_source")
    if src:
        default_pdb = src.split("_raw")[0].split(".")[0].upper()
    return _structure_candidates_for_gene(gene_symbol.upper(), default_pdb)


@app.get("/api/targets/{target_id}/binding_site")
def binding_site(target_id: str):
    """Binding-site evidence for the AUTOMATIC (registry-default) profile:
       the pocket residues within 5 A of the reference ligand, plus the
       center/box_size already stored. Computed fresh from files already on
       disk (raw PDB + cleaned receptor) every call — cheap (no PDBFixer/
       Vina involved) and works retroactively for every already-validated
       target without needing to rebuild anything."""
    if DOCK_PROFILE is None:
        raise HTTPException(503, "Docking package not available")
    try:
        profile = DOCK_PROFILE.load_profile(target_id)
    except Exception as e:
        raise HTTPException(404, str(e))
    from docking import receptor_prep as RP
    resname = profile.get("reference_ligand_resname")
    raw_path = os.path.join(DOCK_PROFILE.DOCKING_TARGETS_DIR, target_id, profile.get("pdb_source") or "")
    residues, error = [], None
    if resname and os.path.exists(raw_path) and profile.get("receptor_pdb") and os.path.exists(profile["receptor_pdb"]):
        try:
            ref_coords = RP.locate_ligand_near(raw_path, resname, profile["center"])
            residues = RP.pocket_residues(profile["receptor_pdb"], ref_coords, cutoff=5.0)
        except Exception as e:
            error = str(e)
    else:
        error = "raw structure or cleaned receptor no longer on disk"
    crystal_sdf = os.path.join(DOCK_PROFILE.DOCKING_TARGETS_DIR, target_id, "crystal_ligand.sdf")
    blind_center = blind_box_size = None
    if profile.get("receptor_pdb") and os.path.exists(profile["receptor_pdb"]):
        try:
            blind_center, blind_box_size = RP.box_from_receptor(profile["receptor_pdb"])
        except Exception:
            pass   # blind mode just won't be offered for this target; site-specific evidence above is unaffected
    return {"target_id": target_id, "center": profile.get("center"), "box_size": profile.get("box_size"),
           "reference_ligand_resname": resname, "pocket_residues": residues, "n_pocket_residues": len(residues),
           "has_reference_ligand_mol": os.path.exists(crystal_sdf),
           "blind_center": blind_center, "blind_box_size": blind_box_size,
           "error": error if not residues else None}


@app.get("/api/targets/{target_id}/reference_ligand.sdf")
def reference_ligand_sdf(target_id: str):
    """The crystal (experimentally-observed) reference-ligand pose, real
       bond orders included — only exists for targets that went through the
       full validate_target.py pipeline (not Advanced Settings' on-demand
       custom structures, which skip this step)."""
    if DOCK_PROFILE is None:
        raise HTTPException(503, "Docking package not available")
    path = os.path.join(DOCK_PROFILE.DOCKING_TARGETS_DIR, target_id, "crystal_ligand.sdf")
    if not os.path.exists(path):
        raise HTTPException(404, f"no reference-ligand pose on file for '{target_id}'")
    return PlainTextResponse(open(path).read())


class BoxFromResiduesBody(BaseModel):
    target_id: str
    residues: List[dict]     # [{chain, resnum}, ...] — from a binding_site/custom_profile response
    receptor_pdb: Optional[str] = None   # pass a custom_profile's receptor_pdb to target that structure instead
    padding: float = 8.0


@app.post("/api/docking/box_from_residues")
def box_from_residues(body: BoxFromResiduesBody):
    """Advanced Settings' 'define the binding site from residues' path:
       user checks residues off the pocket list, this recomputes center/
       box_size from their coordinates (same math as the automatic ligand-
       centered box) — an alternative to typing raw XYZ numbers."""
    if not body.residues:
        raise HTTPException(400, "Pick at least one residue.")
    from docking import receptor_prep as RP
    receptor_pdb = body.receptor_pdb
    if not receptor_pdb:
        if DOCK_PROFILE is None:
            raise HTTPException(503, "Docking package not available")
        try:
            receptor_pdb = DOCK_PROFILE.load_profile(body.target_id)["receptor_pdb"]
        except Exception as e:
            raise HTTPException(404, str(e))
    if not os.path.exists(receptor_pdb):
        raise HTTPException(404, f"receptor file not found: {receptor_pdb}")
    try:
        center, box_size = RP.box_from_residues(receptor_pdb, body.residues, padding=body.padding)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"center": center, "box_size": box_size}


_CUSTOM_RECEPTOR_JOBS = {}


class CustomReceptorBody(BaseModel):
    target_id: str
    pdb_id: str
    chain: Optional[str] = None
    ligand_resname: Optional[str] = None


@app.post("/api/docking/receptor/custom")
def docking_receptor_custom(body: CustomReceptorBody):
    """Advanced Settings' manual structure override: build (strip/repair/
       PDBQT) a receptor for an expert-chosen PDB entry on demand, THEN run
       the same redocking check (scripts/validate_target.py's RMSD<2A gate)
       the automatic/batch pipeline uses — one extra Vina redock of the
       known co-crystallised ligand, ~10-30s, so a manually-picked structure
       doesn't have to stay permanently 'unconfirmed' the way it used to.
       Never touches docking_registry.json regardless of the outcome — this
       is still a per-request profile the caller passes back as
       advanced.custom_profile on submit, so it can't silently overwrite the
       vetted automatic default (or race a concurrent batch_validate.py
       run's registry writes) — 'validated' here just reflects THIS specific
       structure's own redocking result, not a promotion to the registry."""
    import threading, uuid
    if DOCK_PROFILE is None:
        raise HTTPException(503, "Docking package not available")
    from docking import receptor_prep as RP
    from scripts.pdb_fetch import fetch_pdb
    from scripts.detect_chain import chain_for_ligand
    from scripts.batch_validate import gene_for_target

    jid = uuid.uuid4().hex[:12]
    _CUSTOM_RECEPTOR_JOBS[jid] = {"status": "queued", "profile": None, "error": None}

    def work():
        job = _CUSTOM_RECEPTOR_JOBS[jid]
        job["status"] = "running"
        try:
            out_dir = os.path.join("docking_targets", "_custom")
            work_id = f"{body.target_id}__{body.pdb_id}"
            os.makedirs(os.path.join(out_dir, work_id), exist_ok=True)
            raw_pdb = os.path.join(out_dir, work_id, f"{body.pdb_id}_raw.pdb")
            fetch_pdb(body.pdb_id, raw_pdb)
            chain = body.chain
            if not chain and body.ligand_resname:
                chain = chain_for_ligand(raw_pdb, body.ligand_resname)
                if chain is None:
                    raise RuntimeError(f"ligand '{body.ligand_resname}' not found in any chain of {body.pdb_id}")
            profile = RP.build_receptor(raw_pdb, work_id, name=f"{body.target_id} ({body.pdb_id}, manual)",
                                        ref_resname=body.ligand_resname, chain=chain, out_dir=out_dir)
            profile["target_id"] = body.target_id   # advertise the REAL target_id to the caller, not the scratch work_id

            if body.ligand_resname:
                try:
                    from scripts.validate_target import fetch_ligand_smiles, make_crystal_sdf
                    lig_smiles = fetch_ligand_smiles(body.ligand_resname)
                    crystal_sdf = make_crystal_sdf(raw_pdb, body.ligand_resname,
                                                   os.path.join(out_dir, work_id, "crystal_ligand.sdf"),
                                                   lig_smiles, chain=chain)
                    redock = DOCK_PIPE.redock_reference(profile, lig_smiles, crystal_sdf=crystal_sdf, rmsd_threshold=2.0)
                    profile["validated"] = bool(redock.get("validated"))
                    profile["reference_rmsd"] = redock.get("reference_rmsd")
                    if not redock.get("validated"):
                        profile["redock_note"] = (
                            f"redocking RMSD {redock['reference_rmsd']} Å exceeds the 2 Å threshold"
                            if redock.get("reference_rmsd") is not None
                            else f"redocking check inconclusive ({redock.get('rmsd_error') or redock.get('status') or 'no valid pose'})")
                except Exception as e:
                    profile["redock_note"] = f"redocking check errored: {e}"
            else:
                profile["redock_note"] = "no ligand resname given — redocking check skipped"

            job["profile"] = profile
            job["status"] = "done"
        except Exception as e:
            job["status"] = "error"; job["error"] = str(e)
    threading.Thread(target=work, daemon=True).start()
    return {"job_id": jid}


@app.get("/api/docking/receptor/custom/job/{jid}")
def docking_receptor_custom_job(jid: str):
    job = _CUSTOM_RECEPTOR_JOBS.get(jid)
    if not job:
        raise HTTPException(404, "unknown job")
    r = {"status": job["status"]}
    if job["status"] == "done":
        r["profile"] = job["profile"]
    if job["status"] == "error":
        r["error"] = job["error"]
    return r


_AUTO_VALIDATE_JOBS = {}


class AutoValidateBody(BaseModel):
    target_id: str


@app.post("/api/docking/receptor/auto_validate")
def docking_receptor_auto_validate(body: AutoValidateBody):
    """'Find the best validated structure automatically': tries this
       target's ranked candidates (scripts/batch_validate.py's own
       cheap-tier-then-deep-tier candidate list, the same source the manual
       structure picker ranks from) IN ORDER, redocking each one, and keeps
       the first that passes AND is at least as good as whatever's already
       the registry default — exactly scripts/batch_validate.py's own
       run_one()/_try_candidate()/_accept_or_revert() machinery, just
       exposed for a single target on demand instead of only as an offline
       batch script. Works for a QSAR-modeled target_id (e.g.
       CHEMBL1862_ABL1) the same as a no-QSAR-model GENE_<symbol> id —
       gene_for_target() splits either the same way, and a GENE_<symbol>
       target getting a validated registry entry for the first time is
       exactly what turns Automatic mode on for it (previously always
       'manual structure required, no automatic default exists').

       Safe to call whether or not a default already exists: with one, it
       can only replace it with something at least as good (never worse —
       same accept-or-revert protection the offline batch script has, now
       covering the receptor FILES too, not just the registry entry); with
       none, it can only ever set one, never invent a fake pass."""
    import threading, uuid
    if DOCK_PROFILE is None:
        raise HTTPException(503, "Docking package not available")
    jid = uuid.uuid4().hex[:12]
    _AUTO_VALIDATE_JOBS[jid] = {"status": "queued", "result": None, "error": None}

    def work():
        job = _AUTO_VALIDATE_JOBS[jid]
        job["status"] = "running"
        try:
            from scripts import batch_validate as BV
            prior = BV.registry_entry(body.target_id)
            prior_pdb = prior.get("pdb_source") if prior else None
            prior_validated = bool(prior and prior.get("validated"))
            prior_rmsd = prior.get("reference_rmsd") if prior else None
            BV.run_one(body.target_id, skip_validated=False)
            new = BV.registry_entry(body.target_id)
            job["result"] = {
                "was_already_validated": prior_validated,
                "prior_pdb_source": prior_pdb, "prior_reference_rmsd": prior_rmsd,
                "validated": bool(new and new.get("validated")),
                "pdb_source": new.get("pdb_source") if new else None,
                "reference_rmsd": new.get("reference_rmsd") if new else None,
                "changed": bool(new) and (new.get("pdb_source") != prior_pdb or new.get("reference_rmsd") != prior_rmsd),
            }
            job["status"] = "done"
        except Exception as e:
            job["status"] = "error"; job["error"] = str(e)
    threading.Thread(target=work, daemon=True).start()
    return {"job_id": jid}


@app.get("/api/docking/receptor/auto_validate/job/{jid}")
def docking_receptor_auto_validate_job(jid: str):
    job = _AUTO_VALIDATE_JOBS.get(jid)
    if not job:
        raise HTTPException(404, "unknown job")
    r = {"status": job["status"]}
    if job["status"] == "done":
        r["result"] = job["result"]
    if job["status"] == "error":
        r["error"] = job["error"]
    return r


class AdvancedDocking(BaseModel):
    """Every field is optional and defaults to Automatic — set only the ones
       an expert user actually overrode (see PROJECT_DOCUMENTATION.md's
       'Hide complexity, not evidence' principle: Automatic stays the
       default everywhere, this is opt-in per request, never persisted)."""
    exhaustiveness: Optional[int] = Field(default=None, ge=1, le=64)
    n_poses: Optional[int] = Field(default=None, ge=1, le=20)
    use_gnina: Optional[bool] = None          # None = automatic (use if installed); False = force off
    docking_mode: Optional[str] = None        # None/"site_specific" (default) | "blind"
    box_center: Optional[List[float]] = Field(default=None, min_length=3, max_length=3)
    box_size: Optional[List[float]] = Field(default=None, min_length=3, max_length=3)
    custom_profile: Optional[dict] = None     # from /api/docking/receptor/custom's job result


BLIND_CAVEAT = ("Blind docking: searching the ENTIRE protein surface, not a validated (or even assumed) "
                "pocket. Vina must cover a much larger volume than a site-specific box, which is both "
                "slower and substantially less reliable per-site — treat any hit as a candidate binding "
                "site to investigate, not a confirmed pose or affinity. Consider raising exhaustiveness "
                "well above the default 8 for a real blind search.")


def _resolve_docking_setup(target_id, advanced):
    """Turns a (possibly-empty) AdvancedDocking into (profile, engine,
       rescorer, n_poses, caveat) — shared by /api/docking/submit and the
       Screen pipeline so 'automatic unless overridden' behaves identically
       in both places.

       Raises HTTPException the same way the plain-automatic path already
       did when nothing usable is available."""
    from docking.engines import VinaEngine, GninaRescorer, NullRescorer
    adv = advanced or AdvancedDocking()
    blind = (adv.docking_mode == "blind")
    caveat = None

    if adv.custom_profile:
        profile = dict(adv.custom_profile)
        if profile.get("target_id") != target_id:
            raise HTTPException(400, "custom_profile's target_id doesn't match the request's target_id")
        if not profile.get("validated") and not blind:
            caveat = (f"Using a manually-selected structure ({profile.get('pdb_source', '?')}) that has "
                      "NOT passed redocking validation — pose geometry is unconfirmed. Automatic mode "
                      "would have used the redocking-validated default instead.")
    else:
        try:
            profile = DOCK_PROFILE.load_profile(target_id)
        except Exception as e:
            raise HTTPException(404, str(e))
        # Site-specific automatic mode still requires a proven pocket. Blind mode
        # doesn't assume any pocket at all, so it only needs a prepared receptor —
        # it works even for targets whose default site-specific box never validated.
        if not profile.get("validated") and not blind:
            raise HTTPException(409, f"'{target_id}' has not passed redocking validation — its receptor "
                                     "geometry/search box are unconfirmed, so Vina scores for it would be "
                                     "unreliable. Use Advanced Settings to pick a different structure, use "
                                     "Blind docking mode, or see Target Info for its RMSD/enrichment.")

    if blind:
        from docking import receptor_prep as RP
        receptor_pdb = profile.get("receptor_pdb")
        if not receptor_pdb or not os.path.exists(receptor_pdb):
            raise HTTPException(404, f"no prepared receptor on disk for '{target_id}' — blind docking needs "
                                     "at least a stripped/repaired receptor, even without a validated pocket.")
        try:
            center, size = RP.box_from_receptor(receptor_pdb)
        except Exception as e:
            raise HTTPException(500, f"could not compute a blind (whole-protein) box: {e}")
        profile = dict(profile, center=center, box_size=size, site_source="blind_whole_protein")
        caveat = (caveat + " " if caveat else "") + BLIND_CAVEAT
    elif adv.box_center or adv.box_size:
        profile = dict(profile)
        if adv.box_center: profile["center"] = adv.box_center
        if adv.box_size: profile["box_size"] = adv.box_size

    engine = VinaEngine(exhaustiveness=adv.exhaustiveness or 8)
    rescorer = NullRescorer() if adv.use_gnina is False else GninaRescorer()
    n_poses = adv.n_poses or 9
    return profile, engine, rescorer, n_poses, caveat


class DockBody(BaseModel):
    target_id: str
    smiles: List[str]
    advanced: Optional[AdvancedDocking] = None


@app.post("/api/docking/submit")
def docking_submit(body: DockBody):
    import uuid
    if DOCK_AVAIL is None or not DOCK_AVAIL.status()["ready"]:
        raise HTTPException(503, "Docking is not available — install Vina and prep a receptor. See the Docking tab.")
    profile, engine, rescorer, n_poses, caveat = _resolve_docking_setup(body.target_id, body.advanced)
    smiles = [s.strip() for s in body.smiles if s and s.strip()]
    if not smiles:
        raise HTTPException(400, "No SMILES provided.")
    jid = uuid.uuid4().hex[:12]
    # captured now (not read back off job["profile"], which _run_docking_job
    # nulls out once done) — the 3D pose viewer needs the receptor that was
    # ACTUALLY docked against, which for an Advanced Settings custom_profile
    # (any target, not just no-QSAR-model ones) is NOT the same file
    # /api/docking/receptor/{target_id} would serve (that's always the
    # registry's automatic default, wrong receptor for a manual override —
    # and a plain KeyError/500 for a GENE_ target_id, which has no registry
    # entry at all).
    receptor_pdb_path = profile.get("receptor_pdb")
    _DOCK_JOBS[jid] = {"status": "queued", "total": len(smiles), "done": 0, "results": [], "caveat": caveat,
                       "profile": profile, "smiles": smiles, "engine": engine, "rescorer": rescorer, "n_poses": n_poses,
                       "receptor_pdb_path": receptor_pdb_path}
    _run_docking_job(jid)      # background thread
    return {"job_id": jid, "total": len(smiles), "caveat": caveat}


def _run_docking_job(jid):
    import threading
    def work():
        job = _DOCK_JOBS[jid]
        job["status"] = "running"
        try:
            from docking.enrichment import annotate_with_reference
            for s in job["smiles"]:
                result = DOCK_PIPE.dock_compound(
                    job["profile"], s, engine=job["engine"], rescorer=job["rescorer"],
                    n_poses=job["n_poses"], make_diagram=True)
                # FREE per-compound comparison against the target's already-
                # saved active/decoy distribution (no extra docking) — see
                # docking/enrichment.py for eligibility rules. No-ops silently
                # (result unchanged) for unvalidated/custom/blind targets or
                # targets with no saved reference yet.
                annotate_with_reference(result, job["profile"].get("target_id"), job["profile"])
                job["results"].append(result)
                job["done"] += 1
            job["status"] = "done"; job["smiles"] = None; job["profile"] = None
            job["engine"] = None; job["rescorer"] = None
        except Exception as e:
            job["status"] = "error"; job["error"] = str(e)
    threading.Thread(target=work, daemon=True).start()


@app.get("/api/docking/job/{jid}")
def docking_job(jid: str):
    job = _DOCK_JOBS.get(jid)
    if not job:
        raise HTTPException(404, "unknown job")
    r = {"status": job["status"], "done": job["done"], "total": job["total"], "caveat": job.get("caveat")}
    if job["status"] == "done":
        r["results"] = job["results"]
        r["receptor_pdb_path"] = job.get("receptor_pdb_path")
    if job["status"] == "error":
        r["error"] = job.get("error")
    return r


class FreshDecoyBody(BaseModel):
    target_id: str
    smiles: str
    advanced: Optional[AdvancedDocking] = None
    n_decoys: int = Field(default=50, ge=5, le=200)


_ENRICHMENT_JOBS = {}


@app.post("/api/docking/enrichment/fresh")
def enrichment_fresh_submit(body: FreshDecoyBody):
    """The EXPENSIVE, on-demand tier (see docking/enrichment.py's module
       docstring): ~(n_decoys + 1) fresh Vina runs against NEW decoys
       property-matched to THIS specific compound, using the exact same
       profile (receptor/box/exhaustiveness) the caller would submit for a
       normal dock — pass the same `advanced` block a prior /api/docking/
       submit call for this compound used, so the comparison is apples-to-
       apples with whatever structure/mode that used (including a manually-
       picked Advanced Settings structure, which the free per-compound
       annotation on /api/docking/submit deliberately skips)."""
    import uuid, threading
    if DOCK_AVAIL is None or not DOCK_AVAIL.status()["ready"]:
        raise HTTPException(503, "Docking is not available — install Vina and prep a receptor. See the Docking tab.")
    if not body.smiles.strip():
        raise HTTPException(400, "No SMILES provided.")
    profile, engine, rescorer, n_poses, caveat = _resolve_docking_setup(body.target_id, body.advanced)
    jid = uuid.uuid4().hex[:12]
    _ENRICHMENT_JOBS[jid] = {"status": "queued", "result": None, "error": None, "done": 0, "total": body.n_decoys + 1}

    def work():
        job = _ENRICHMENT_JOBS[jid]
        job["status"] = "running"
        try:
            from docking.enrichment import fresh_decoy_validation

            def on_progress(done, total):
                job["done"] = done
                job["total"] = total

            job["result"] = fresh_decoy_validation(body.target_id, body.smiles, profile,
                                                    engine=engine, n_decoys=body.n_decoys, progress_cb=on_progress)
            job["status"] = "done"
        except Exception as e:
            job["status"] = "error"; job["error"] = str(e)
    threading.Thread(target=work, daemon=True).start()
    return {"job_id": jid}


@app.get("/api/docking/enrichment/fresh/job/{jid}")
def enrichment_fresh_job(jid: str):
    job = _ENRICHMENT_JOBS.get(jid)
    if not job:
        raise HTTPException(404, "unknown job")
    r = {"status": job["status"], "done": job.get("done", 0), "total": job.get("total")}
    if job["status"] == "done":
        r["result"] = job["result"]
    if job["status"] == "error":
        r["error"] = job.get("error")
    return r


# ---------------- screen (the full STEP 1-8 pipeline, CLAUDE.md §7.1) ----------------
from serving import screen as SCREEN

_SCREEN_JOBS = {}


class ScreenBody(BaseModel):
    target_id: str
    smiles: List[str]
    advanced: Optional[AdvancedDocking] = None


@app.post("/api/screen/submit")
def screen_submit(body: ScreenBody):
    import uuid
    smiles = [s.strip() for s in body.smiles if s and s.strip()]
    if not smiles:
        raise HTTPException(400, "No SMILES provided.")
    if body.target_id not in MA.list_target_ids():
        raise HTTPException(404, f"Unknown target '{body.target_id}'")
    jid = uuid.uuid4().hex[:12]
    _SCREEN_JOBS[jid] = {"status": "queued", "step": 0, "step_label": "Queued",
                         "done": None, "total": None, "result": None, "error": None}
    _run_screen_job(jid, body.target_id, smiles, body.advanced.model_dump() if body.advanced else None)
    return {"job_id": jid}


def _run_screen_job(jid, target_id, smiles, advanced=None):
    import threading

    def on_progress(step, label, done=None, total=None):
        job = _SCREEN_JOBS[jid]
        job["step"] = step; job["step_label"] = label; job["done"] = done; job["total"] = total

    def work():
        job = _SCREEN_JOBS[jid]
        job["status"] = "running"
        try:
            result = SCREEN.run(target_id, smiles, progress=on_progress, advanced=advanced)
            job["result"] = result
            job["status"] = "done"
        except Exception as e:
            job["status"] = "error"; job["error"] = str(e)
    threading.Thread(target=work, daemon=True).start()


@app.get("/api/screen/job/{jid}")
def screen_job(jid: str):
    job = _SCREEN_JOBS.get(jid)
    if not job:
        raise HTTPException(404, "unknown job")
    r = {"status": job["status"], "step": job["step"], "step_label": job["step_label"],
        "total_steps": 8, "done": job["done"], "total": job["total"]}
    if job["status"] == "done":
        r["result"] = job["result"]
    if job["status"] == "error":
        r["error"] = job.get("error")
    return r


@app.get("/api/screen/job/{jid}/export.csv")
def screen_export_csv(jid: str):
    from fastapi.responses import StreamingResponse
    import io
    job = _SCREEN_JOBS.get(jid)
    if not job or job["status"] != "done":
        raise HTTPException(404, "job not found or not finished")
    rows = job["result"]["shortlist"]
    df = pd.DataFrame([{
        "rank": r["rank"], "input_smiles": r["input_smiles"], "smiles": r["smiles"],
        "predicted_pIC50": r["qsar"]["predicted_pIC50"], "in_domain": r["qsar"]["in_domain"],
        "qsar_confidence": r["qsar"]["confidence"],
        "vina_score": (r["docking"] or {}).get("vina_score"),
        "docking_confidence": (r["docking"] or {}).get("confidence"),
        "fused_score": r["fused_score"], "caveats": "; ".join(r["caveats"]),
    } for r in rows])
    buf = io.StringIO(); df.to_csv(buf, index=False); buf.seek(0)
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": f'attachment; filename="screen_{jid}.csv"'})


