"""
============================================================
  ADMET-AI WORKER SERVICE  (admet_service.py)
============================================================
  Runs ADMET-AI in its OWN process so its heavy CPU load is isolated
  from the main web app (potency/compare tabs stay responsive).

  Run it separately, e.g. on port 8100:
      pip install admet-ai
      uvicorn admet_service:app --host 127.0.0.1 --port 8100

  The main app talks to it over HTTP (ADMET_SERVICE_URL). If this worker
  is not running, the main app falls back to the deterministic layer.

  Endpoints:
      GET  /health              -> {available}
      POST /profile {smiles[]}  -> synchronous, for small lists (<=1000)
      POST /jobs    {smiles[]}  -> async job for large lists -> {job_id}
      GET  /jobs/{id}           -> {status, done, total, predictions?}

  Jobs are processed by ONE background thread (sequential), so multiple
  big runs queue instead of thrashing all CPU cores at once.
============================================================
"""
import os

# --- CPU hygiene: cap threads so ADMET-AI does not hog a shared box ---
os.environ.setdefault("OMP_NUM_THREADS", "4")
os.environ.setdefault("MKL_NUM_THREADS", "4")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "4")
os.environ["TQDM_DISABLE"] = "1"                 # silence progress bars

# ADD THESE
os.environ["PYTORCH_LIGHTNING_DISABLE_PROGRESS_BAR"] = "1"

import logging, warnings, threading, queue, uuid

# ADD THIS
logging.getLogger("lightning.pytorch.utilities.rank_zero").setLevel(logging.ERROR)

for _n in ("lightning.pytorch", "pytorch_lightning", "lightning", "chemprop"):
    logging.getLogger(_n).setLevel(logging.ERROR)

warnings.filterwarnings("ignore")

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List
import pandas as pd

app = FastAPI(title="PhytoScreen ADMET worker", version="1.0")

BATCH = 512
_MODEL = None
_ERR = None

def get_model():
    global _MODEL, _ERR
    if _MODEL is not None:
        return _MODEL
    try:
        from admet_ai import ADMETModel
        _MODEL = ADMETModel()
    except Exception as e:
        _ERR = str(e); _MODEL = None
    return _MODEL

@app.on_event("startup")
def _warm():
    get_model()                                  # load once at startup, not on first request

def _predict(smiles):
    m = get_model()
    if m is None:
        return None
    preds = m.predict(smiles=list(smiles))
    if not isinstance(preds, pd.DataFrame):
        preds = pd.DataFrame([preds], index=list(smiles))
    return preds.to_dict("index")

# ---- job queue (single worker thread) ----
JOBS = {}
_Q = queue.Queue()

def _loop():
    while True:
        jid = _Q.get()
        job = JOBS.get(jid)
        if job:
            try:
                job["status"] = "running"
                smis, out = job["smiles"], {}
                for i in range(0, len(smis), BATCH):
                    res = _predict(smis[i:i + BATCH])
                    if res is None:
                        job["status"] = "error"; job["error"] = _ERR or "model unavailable"; break
                    out.update(res); job["done"] = min(i + BATCH, len(smis))
                else:
                    job["predictions"] = out; job["status"] = "done"; job["smiles"] = None
            except Exception as e:
                job["status"] = "error"; job["error"] = str(e)
        _Q.task_done()

threading.Thread(target=_loop, daemon=True).start()

class Batch(BaseModel):
    smiles: List[str]

@app.get("/health")
def health():
    return {"available": get_model() is not None, "source": "ADMET-AI", "error": _ERR}

@app.post("/profile")
def profile(b: Batch):
    if len(b.smiles) > 1000:
        raise HTTPException(413, "list too large for /profile; use /jobs")
    res = _predict(b.smiles)
    if res is None:
        return {"available": False, "error": _ERR}
    return {"available": True, "predictions": res}

@app.post("/jobs")
def submit(b: Batch):
    jid = uuid.uuid4().hex[:12]
    JOBS[jid] = {"status": "queued", "total": len(b.smiles), "done": 0,
                 "smiles": b.smiles, "predictions": None}
    _Q.put(jid)
    return {"job_id": jid, "total": len(b.smiles)}

@app.get("/jobs/{jid}")
def job_status(jid: str):
    j = JOBS.get(jid)
    if not j:
        raise HTTPException(404, "unknown job")
    r = {"status": j["status"], "done": j["done"], "total": j["total"]}
    if j["status"] == "done":
        r["predictions"] = j["predictions"]
    if j["status"] == "error":
        r["error"] = j.get("error")
    return r