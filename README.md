# PhytoScreen

A local, offline, CPU-only tool for prioritising compounds against a
validated biological target — QSAR potency (Chemprop + AutoGluon), ADMET
profiling, and structure-based docking. Two independent services: a FastAPI
JSON API (`backend/`) and a React single-page UI (`frontend/`), talking to
each other over HTTP/CORS — there is no longer a bundled desktop window.

## Layout

    backend/                 FastAPI JSON API — no UI, no static files
      app.py                   mounts predict/admet/docking/screen
                                + the factory_browser router (Target Info tab)
      serving/                 the only code that knows the model-bucket format
        model_adapter.py         loads a target bucket (AutoGluon + Chemprop), predicts
        featurize.py              SMILES -> the exact training feature space
        applicability.py          AD z-score gating
        confidence.py             honest confidence tiers (target test RMSE, not a
                                   fabricated per-compound interval)
        screen.py                 the STEP 1-8 Screen pipeline orchestration
      analysis.py               multi-target / disease comparison
      admet.py / admet_service.py / admet_endpoints.py   ADMET deterministic
                                layer + isolated ADMET-AI worker process
      factory_browser.py       /api/factory/* — browse + download every file in
                                a target's bucket (Target Info tab)
      docking/                  receptor prep, ligand prep, Vina engine, PoseBusters
                                gate, pose consensus, RMSD, PLIP+LigPlot-style 2D
                                interaction diagrams (falls back to a built-in
                                distance-based detector if PLIP isn't installed)
      scripts/, tests/          offline tooling + the API test suite
      requirements.txt
    frontend/                React + TypeScript + Tailwind UI: Screen / Predict /
                             ADMET / Compare / Docking / Target Info
    models/<target_id>/      per-target buckets (read-only input; see CLAUDE.md §5)
    docking_targets/<id>/    prepared receptors (read-only input)
    docking_registry.json    docking targets + validation (portable relative paths)

`models/`, `docking_targets/` and `docking_registry.json` sit at the repo
root, as siblings of `backend/` — the backend resolves them relative to its
**working directory**, not its own file location, so it must always be run
from the repo root (see below), not from inside `backend/`.

## Run the backend

From the repo root:

    cd backend
    pip install -r requirements.txt   # + torch CPU wheel, see the file's header
    cd ..
    uvicorn app:app --app-dir backend --host 127.0.0.1 --port 8000 --reload

`--app-dir backend` puts `backend/` on `sys.path` (so `import app`, `docking`,
`serving`, etc. resolve) while keeping the working directory at the repo
root (so `models/`, `docking_targets/`, `docking_registry.json` resolve).

Start the ADMET-AI worker separately if you want the learned ADMET layer
(optional — the deterministic layer always works without it):

    uvicorn admet_service:app --app-dir backend --host 127.0.0.1 --port 8100

Run the test suite the same way (from the repo root, so it sees the same
data directories):

    pytest backend/tests

## Run the frontend

    cd frontend
    npm install
    npm run dev      # Vite dev server on :5173, proxies /api to :8000 — zero config
    npm run build    # standalone production build -> frontend/dist/

The dev server's proxy is a same-origin convenience only. A built frontend
(`frontend/dist/`, served by anything — `vite preview`, nginx, a CDN) talks to
the backend directly over CORS: set `VITE_API_BASE=http://your-backend-host:8000`
at build time (see `frontend/.env.example`), and set `ALLOWED_ORIGINS` on the
backend to the frontend's real origin (defaults to `*` — fine for local/
single-user use, since there's no cookie-based auth to protect).
