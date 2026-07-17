"""
============================================================
  PhytoScreen — Serving App backend (app.py)
============================================================
  Prediction-first serving app. NO training here. Reads a registry.json
  copied from the model factory + the .pkl files you copy into models/.

  Run:
      pip install rdkit scikit-learn scipy pandas numpy pyyaml \
                  fastapi "uvicorn[standard]" python-multipart
      uvicorn app:app --host 0.0.0.0 --port 8000
      open http://localhost:8000/

  Tabs served by one single-page UI: Predict / ADMET / Compare / Docking.
============================================================
"""
import os
import warnings
warnings.filterwarnings("ignore")

import pandas as pd
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional, List

import serve
import pipeline as P
import analysis as A
import admet as ADMET

_here = os.path.dirname(os.path.abspath(__file__))
try:
    import yaml
    with open(os.path.join(_here, "diseases.yaml")) as _f:
        _DISEASES = {d["id"]: d for d in (yaml.safe_load(_f) or {}).get("diseases", [])}
except Exception:
    _DISEASES = {}

app = FastAPI(title="PhytoScreen", version="2.0")

DISCLAIMER = ("Prioritisation aid, not a substitute for assays. Trust predictions only for "
              "in-domain molecules; treat the top of the list as a shortlist.")


def _num(v):
    try:
        if v is None or pd.isna(v):
            return None
        return round(float(v), 3)
    except Exception:
        return None


def confidence_tier(width, in_ad):
    if not in_ad:
        return "out", "Outside training chemistry"
    if width is None:
        return "med", "Medium confidence"
    if width <= 1.5:
        return "high", "High confidence"
    if width <= 3.0:
        return "med", "Medium confidence"
    return "low", "Low confidence (wide range)"


def _rows(df, lower_col, in_ad_flag):
    out, has_pi = [], "PI_low" in df.columns
    for _, r in df.iterrows():
        width = (r["PI_high"] - r["PI_low"]) if has_pi else None
        tier, label = confidence_tier(width, in_ad_flag)
        row = {"smiles": r.get("Standardised_SMILES"), "input_smiles": r.get("Input_SMILES"),
               "predicted": _num(r.get("Predicted_pIC50")),
               "lower": _num(r.get(lower_col)) if lower_col in df.columns else None,
               "pi_low": _num(r.get("PI_low")) if has_pi else None,
               "pi_high": _num(r.get("PI_high")) if has_pi else None,
               "ad_distance": _num(r.get("AD_distance")),
               "in_domain": bool(in_ad_flag), "confidence": tier, "confidence_label": label}
        if "Rank" in df.columns:
            row["rank"] = int(r["Rank"])
        out.append(row)
    return out


def _predict(target_id, smiles, model_name):
    try:
        asset, rec = serve.load_model(target_id)
    except KeyError:
        raise HTTPException(404, f"Unknown target '{target_id}'")
    except (RuntimeError, FileNotFoundError) as e:
        raise HTTPException(409, str(e))
    if not smiles:
        raise HTTPException(400, "No SMILES provided.")
    in_dom, out_dom, sort_col, rec, model_name = serve.rank(target_id, smiles, model_name=model_name)
    conf = P._conformal_for(asset, model_name)
    lvl = int(round(conf["confidence"] * 100)) if conf else 90
    lower_col = f"Lower_{lvl}"
    bad = out_dom[~out_dom["Parsed_OK"]] if "Parsed_OK" in out_dom.columns else out_dom.iloc[0:0]
    out_real = out_dom[out_dom["Parsed_OK"]] if "Parsed_OK" in out_dom.columns else out_dom
    m = rec.get("metrics_by_model", {}).get(model_name, {})
    return {"target": {"id": rec["target_id"], "name": rec["name"], "status": rec["status"]},
            "model": model_name, "is_best": model_name == asset["best_name"],
            "interval_status": rec.get("interval_status", "approximate"), "confidence_pct": lvl,
            "model_metrics": {"test_r2": m.get("test_r2"), "spearman": m.get("spearman"),
                              "top_pick_pct": m.get("top_pick_pct"), "coverage": m.get("conformal_coverage")},
            "counts": {"in_domain": int(len(in_dom)), "out_of_domain": int(len(out_real)),
                       "skipped": int(len(bad)), "submitted": int(len(smiles))},
            "in_domain": _rows(in_dom, lower_col, True), "out_of_domain": _rows(out_real, lower_col, False),
            "skipped": [str(s) for s in bad.get("Input_SMILES", pd.Series([])).tolist()],
            "ranked_by": sort_col, "disclaimer": DISCLAIMER}


# ---------------- models ----------------
class PredictBody(BaseModel):
    target_id: str
    smiles: List[str]
    model: Optional[str] = None


class MultiBody(BaseModel):
    smiles: List[str]
    target_ids: Optional[List[str]] = None
    disease_id: Optional[str] = None
    model: Optional[str] = None


@app.get("/api/health")
def health():
    reg = serve.load_registry()
    avail = sum(1 for r in reg.values() if serve.asset_available(r))
    try:
        dock_ready = bool(DOCK_AVAIL and DOCK_AVAIL.status()["ready"])
    except Exception:
        dock_ready = False
    return {"models_in_registry": len(reg), "models_available": avail,
            "admet_ai": ADMET.learned_status()["available"],
            "docking": "ready" if dock_ready else "not_ready", "disclaimer": DISCLAIMER}


@app.get("/api/targets")
def targets():
    reg = serve.load_registry()
    out = []
    for tid, r in reg.items():
        m = r.get("metrics", {})
        avail = serve.asset_available(r)
        out.append({"target_id": tid, "name": r.get("name"), "status": r.get("status"),
                    "best_model": r.get("best_model"), "n_compounds": r.get("n_compounds"),
                    "spearman": m.get("spearman_mean"), "interval_status": r.get("interval_status"),
                    "available": avail, "usable": avail and r.get("status") in ("live", "experimental")})
    out.sort(key=lambda x: (not x["usable"], x["status"] != "live", x["name"] or ""))
    return {"targets": out}


@app.get("/api/targets/{tid}/models")
def models(tid: str):
    try:
        asset, rec = serve.load_model(tid)
    except KeyError:
        raise HTTPException(404, f"Unknown target '{tid}'")
    except (RuntimeError, FileNotFoundError) as e:
        raise HTTPException(409, str(e))
    bm = rec.get("metrics_by_model", asset.get("metrics_by_model", {}))
    return {"best_model": asset["best_name"],
            "models": [{"name": n, "is_best": n == asset["best_name"], **bm.get(n, {})}
                       for n in P.list_models(asset)]}


@app.post("/api/predict")
def predict(body: PredictBody):
    return _predict(body.target_id, [s.strip() for s in body.smiles if s and s.strip()], body.model)


@app.post("/api/predict_csv")
async def predict_csv(target_id: str = Form(...), file: UploadFile = File(...),
                      model: Optional[str] = Form(None)):
    import io
    df = pd.read_csv(io.BytesIO(await file.read()))
    col = "SMILES" if "SMILES" in df.columns else ("smiles" if "smiles" in df.columns else df.columns[0])
    smiles = [str(s).strip() for s in df[col].dropna().tolist() if str(s).strip()]
    return _predict(target_id, smiles, model)


@app.get("/api/diseases")
def diseases():
    reg = serve.load_registry()
    usable = {tid for tid, r in reg.items()
              if serve.asset_available(r) and r.get("status") in ("live", "experimental")}
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
        targets = d["targets"]
    elif body.target_ids:
        targets = body.target_ids
    else:
        raise HTTPException(400, "Provide target_ids or disease_id.")
    result = A.analyse(smiles, targets, model=body.model)
    if not result["targets"]:
        raise HTTPException(409, f"No usable targets among {targets}.")
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


# ---------------- single-page UI ----------------
_static = os.path.join(_here, "static")
if os.path.isdir(_static):
    @app.get("/")
    def index():
        return FileResponse(os.path.join(_static, "index.html"))
    app.mount("/static", StaticFiles(directory=_static), name="static")