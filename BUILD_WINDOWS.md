# PhytoScreen Desktop — Windows build (.exe)

A native window (PyWebview) wrapping the FastAPI backend (`app.py`), which
loads real target buckets from `models/<target_id>/` — AutoGluon +
Chemprop, CPU-only, no training, no GPU. See `CLAUDE.md` for the full spec
and `README.md` for the repository layout.

## 1. Install (on the Windows machine, in a venv)
    python -m venv .venv
    .venv\Scripts\activate
    pip install torch --index-url https://download.pytorch.org/whl/cpu
    pip install -r requirements.txt

    # optional, for gold-standard interaction typing (falls back to a
    # built-in distance-based detector if absent — the app still works):
    conda install -c conda-forge plip openbabel

AutoDock Vina (the docking engine) and, optionally, GNINA are external
binaries — install them separately and keep them on PATH. Docking degrades
gracefully (the Docking tab shows exactly what's missing) if they aren't.

## 2. Point the app at your data
    set TARGETS_DIR=C:\path\to\models              (default: .\models)
    set DOCKING_REGISTRY=C:\path\to\docking_registry.json   (default: .\docking_registry.json)
    set DOCKING_TARGETS_DIR=C:\path\to\docking_targets       (default: .\docking_targets)

`docking_registry.json` stores receptor filenames as portable basenames
(e.g. `receptor.pdbqt`), resolved at load time relative to
`DOCKING_TARGETS_DIR/<target_id>/` — so the registry survives moving the
project folder or packaging it into an .exe, unlike an absolute path baked
in at prep time.

## 3. Run in dev first (confirm it works before packaging)
    python desktop.py
A native PhytoScreen window opens. If pywebview can't find a usable GUI
backend at runtime (rare on real Windows — it uses the built-in Edge
WebView2 backend there) it falls back to printing a localhost URL to open
in a browser instead, rather than crashing.

Start the ADMET-AI worker separately if you want the learned ADMET layer
(optional; the deterministic layer always works without it):
    uvicorn admet_service:app --host 127.0.0.1 --port 8100

## 4. Build the .exe (PyInstaller)
From the project folder:
    pip install pyinstaller
    pyinstaller --noconfirm --windowed --name PhytoScreen ^
      --add-data "static;static" ^
      --add-data "docking;docking" ^
      --add-data "diseases.yaml;." ^
      --add-data "docking_registry.json;." ^
      --collect-all rdkit ^
      --collect-all autogluon ^
      --collect-all chemprop ^
      --collect-all lightning ^
      --collect-all posebusters ^
      --collect-all meeko ^
      --collect-all gemmi ^
      --hidden-import lightgbm ^
      --hidden-import catboost ^
      --hidden-import xgboost ^
      --hidden-import uvicorn ^
      desktop.py
The .exe lands in `dist\PhytoScreen\PhytoScreen.exe`. Ship the `models/`
and `docking_targets/` folders alongside it (or point `TARGETS_DIR` /
`DOCKING_TARGETS_DIR` at wherever you keep them — they don't need to be
bundled into the .exe itself, and shouldn't be: buckets are hundreds of MB
each).

### Why `--hidden-import lightgbm/catboost/xgboost`
AutoGluon's stacked ensembles are built from these base learners — the
chosen model for several real targets in this repo is `LightGBMXT_BAG_L1`
or a `CatBoost_BAG_*` child. AutoGluon `pickle.load()`s them lazily at
*predict* time, not at `TabularPredictor.load()` time, so a missing base
learner doesn't fail until the first `/api/predict` call — plan for that
during testing, don't assume "the app started fine" means every target
works. (This bit us during development: the base venv install had
`autogluon.tabular` but not `lightgbm`, and predictions crashed with
`ModuleNotFoundError: No module named 'lightgbm'` the first time a
LightGBM-based target was actually queried.)

Notes / likely tweaks (validate on your machine):
- PyInstaller sometimes needs extra `--collect-all`/`--hidden-import` entries
  beyond this list; if the .exe reports a missing module at launch (or on
  first predict against a specific target — see above), add it and rebuild.
- First launch is slow (unpacking); subsequent launches are fast.
- Loading a target bucket the first time takes ~10s (AutoGluon + the
  Chemprop checkpoint); it's cached in memory afterwards (bounded to
  `PHYTO_MODEL_CACHE_SIZE`, default 2 targets, since buckets can exceed
  500MB each).

## What is tested vs validate-on-Windows
TESTED (CPU-only Linux venv, real target buckets, real FastAPI TestClient —
see `tests/`): featurisation parity + drift self-check, applicability-domain
gating (including the API-boundary guarantee that out-of-domain compounds
never get a potency number), confidence tiers, the model adapter against
real AutoGluon+Chemprop buckets (including a regression test for an extreme-
input crash found and fixed during development), the full predict/admet/
docking-status/screen/factory-browser API surface, the Screen pipeline
end-to-end, docking unit tests (GNINA-capped confidence, a real PoseBusters
check, availability reporting), path-traversal blocked on bucket downloads,
`desktop.py`'s free-port launch + background server thread + health-check
wait, and pywebview's graceful URL fallback when no GUI backend loads
(verified by literally breaking pywebview's backend detection in this
Linux sandbox, which lacks GTK/Qt bindings that aren't relevant on Windows
anyway).

VALIDATE ON YOUR WINDOWS MACHINE: the actual native window rendering (this
sandbox has no GTK/Qt bindings for pywebview to use — Windows doesn't need
them, it uses Edge WebView2), the PyInstaller `.exe` packaging itself, and a
real PLIP/Vina run (PLIP has a graceful fallback to the built-in
distance-based interaction detector; Vina is a hard requirement for docking
to activate at all, with a clear "not ready" status and installation
checklist in the Docking tab if it's missing).
