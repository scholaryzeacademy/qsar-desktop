# PhytoScreen — Serving App

This directory is the **serving app only**. Model training happens in your separate
**factory**; here you just drop in the finished models and run the UI.

## 1. Install (once)
```
pip install -r requirements.txt
```

## 2. Add your models (copied from the factory)
```
serving_app/
  registry.json          <- copy from the factory
  models/                <- copy the .pkl files you need (flat or in per-target folders,
    cox2_qsar_model.pkl     both work; the loader searches by filename)
    ache_qsar_model.pkl
    ...
```
You only need the `.pkl` files for the targets you want live. A target listed in
`registry.json` whose `.pkl` is missing is shown as unavailable — no crash.

## 3. Run
```
uvicorn app:app --host 0.0.0.0 --port 8000
```
Open **http://localhost:8000/** — one page, four tabs:
- **Predict** — rank molecules against one target (paste SMILES or upload CSV)
- **ADMET** — drug-likeness / structural-alert profile (flags, never filters)
- **Compare** — screen across a disease group or several targets (matrix, ranking,
  selectivity, multi-target, best-per-target, ADMET)
- **Docking** — reserved (coming soon)

## Files
| File | Role |
|---|---|
| `app.py` | FastAPI backend (the API) |
| `serve.py` | loads registry + model `.pkl` files (robust path resolution) |
| `pipeline.py` | shared engine: featurisation, prediction, conformal, screening |
| `admet.py` | ADMET deterministic layer + learned-suite adapter |
| `analysis.py` | multi-target / disease comparison engine |
| `diseases.yaml` | disease → target groups (edit to add diseases) |
| `static/index.html` | the single-page UI |
| `registry.json` | *you copy this from the factory* |
| `models/` | *you copy the `.pkl` files here* |

## Notes
- Assets are cached in memory. If you **replace** a model file while the server runs,
  restart uvicorn. Newly **added** targets appear on browser refresh.
- To add a disease group, edit `diseases.yaml` (list existing target ids).
- Learned ADMET endpoints (hERG, AMES, …) are an adapter — integrate a pretrained
  open suite via `admet.register_learned_suite()` to enable them.

## ADMET-AI runs as a SEPARATE worker (isolated CPU)
The learned ADMET endpoints (hERG, AMES, CYPs, BBB, Caco-2, solubility, …) run in
their own process, `admet_service.py`, so a large ADMET job cannot freeze the
potency/compare tabs on a shared server. The main app talks to it over HTTP.

**Run both (easiest):**
```
pip install admet-ai        # on the machine that will run the worker
./run.sh                    # starts the worker (:8100) + main app (:8000)
```

**Or run them by hand:**
```
uvicorn admet_service:app --host 127.0.0.1 --port 8100     # worker (ADMET-AI)
export ADMET_SERVICE_URL=http://127.0.0.1:8100
uvicorn app:app --host 0.0.0.0 --port 8000                 # main app
```

Behaviour:
- **Small ADMET requests** (<=50 molecules) are answered synchronously.
- **Large requests** become a background job in the worker; the UI shows a progress
  bar and polls until done — the main app is never blocked.
- Jobs are processed **one at a time** in the worker, so several big runs queue
  instead of thrashing all CPU cores.
- If the worker is **not running**, the ADMET tab still works with the deterministic
  layer and shows a clear notice. Nothing crashes.
- No GPU needed. Thread counts are capped (OMP/MKL=4) so the worker is a good
  citizen on a shared box; adjust in `admet_service.py` if you have more cores.

Endpoint grouping/labels are editable in `admet_endpoints.py`.