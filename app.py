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
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional, List

from serving import model_adapter as MA
import analysis as A
import admet as ADMET
import factory_browser

_here = os.path.dirname(os.path.abspath(__file__))
try:
    import yaml
    with open(os.path.join(_here, "diseases.yaml")) as _f:
        _DISEASES = {d["id"]: d for d in (yaml.safe_load(_f) or {}).get("diseases", [])}
except Exception:
    _DISEASES = {}

app = FastAPI(title="PhytoScreen", version="3.0")
app.include_router(factory_browser.router)

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
    disease_id: Optional[str] = None


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


@app.get("/api/diseases")
def diseases():
    usable = set(MA.list_target_ids())
    return {"diseases": [{"disease_id": did, "name": d.get("name"), "note": d.get("note"),
                          "targets": d.get("targets", []),
                          "available_targets": [t for t in d.get("targets", []) if t in usable]}
                         for did, d in _DISEASES.items()]}


@app.post("/api/predict_multi")
def predict_multi(body: MultiBody):
    smiles = [s.strip() for s in body.smiles if s and s.strip()]
    if not smiles:
        raise HTTPException(400, "No SMILES provided.")
    if body.disease_id:
        d = _DISEASES.get(body.disease_id)
        if not d:
            raise HTTPException(404, f"Unknown disease '{body.disease_id}'")
        target_ids = d["targets"]
    elif body.target_ids:
        target_ids = body.target_ids
    else:
        raise HTTPException(400, "Provide target_ids or disease_id.")
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
    _DOCK_IMPORT_ERR = None
except Exception as e:
    DOCK_AVAIL = DOCK_PIPE = DOCK_PROFILE = None
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
        st["docking_targets"] = list(reg.keys())
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
    return {"targets": [{"target_id": t, "name": r.get("name", t)} for t, r in reg.items()]}


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


class DockBody(BaseModel):
    target_id: str
    smiles: List[str]


@app.post("/api/docking/submit")
def docking_submit(body: DockBody):
    import uuid
    if DOCK_AVAIL is None or not DOCK_AVAIL.status()["ready"]:
        raise HTTPException(503, "Docking is not available — install Vina and prep a receptor. See the Docking tab.")
    try:
        profile = DOCK_PROFILE.load_profile(body.target_id)
    except Exception as e:
        raise HTTPException(404, str(e))
    smiles = [s.strip() for s in body.smiles if s and s.strip()]
    if not smiles:
        raise HTTPException(400, "No SMILES provided.")
    jid = uuid.uuid4().hex[:12]
    _DOCK_JOBS[jid] = {"status": "queued", "total": len(smiles), "done": 0, "results": [],
                       "profile": profile, "smiles": smiles}
    _run_docking_job(jid)      # background thread
    return {"job_id": jid, "total": len(smiles)}


def _run_docking_job(jid):
    import threading
    def work():
        job = _DOCK_JOBS[jid]
        job["status"] = "running"
        try:
            for s in job["smiles"]:
                job["results"].append(DOCK_PIPE.dock_compound(job["profile"], s, make_diagram=True))
                job["done"] += 1
            job["status"] = "done"; job["smiles"] = None; job["profile"] = None
        except Exception as e:
            job["status"] = "error"; job["error"] = str(e)
    threading.Thread(target=work, daemon=True).start()


@app.get("/api/docking/job/{jid}")
def docking_job(jid: str):
    job = _DOCK_JOBS.get(jid)
    if not job:
        raise HTTPException(404, "unknown job")
    r = {"status": job["status"], "done": job["done"], "total": job["total"]}
    if job["status"] == "done":
        r["results"] = job["results"]
    if job["status"] == "error":
        r["error"] = job.get("error")
    return r


# ---------------- screen (the full STEP 1-8 pipeline, CLAUDE.md §7.1) ----------------
from serving import screen as SCREEN

_SCREEN_JOBS = {}


class ScreenBody(BaseModel):
    target_id: str
    smiles: List[str]


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
    _run_screen_job(jid, body.target_id, smiles)
    return {"job_id": jid}


def _run_screen_job(jid, target_id, smiles):
    import threading

    def on_progress(step, label, done=None, total=None):
        job = _SCREEN_JOBS[jid]
        job["step"] = step; job["step_label"] = label; job["done"] = done; job["total"] = total

    def work():
        job = _SCREEN_JOBS[jid]
        job["status"] = "running"
        try:
            result = SCREEN.run(target_id, smiles, progress=on_progress)
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


# ---------------- single-page UI ----------------
_static = os.path.join(_here, "static")
if os.path.isdir(_static):
    @app.get("/")
    def index():
        return FileResponse(os.path.join(_static, "index.html"))
    app.mount("/static", StaticFiles(directory=_static), name="static")
