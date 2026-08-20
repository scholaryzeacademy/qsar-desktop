# PhytoScreen Desktop — Windows build (.exe)

A native window (PyWebview) wrapping the existing FastAPI JSON API
(`backend/app.py`, unchanged) plus the built frontend (`frontend/dist/`),
served from one process on one localhost port — see `desktop.py`. Model
inference loads real target buckets from `models/<target_id>/`
(AutoGluon + Chemprop, CPU-only, no training, no GPU — see
`PROJECT_DOCUMENTATION.md`).

Unlike the old (pre-`890ebeb`) build, `models/` and `docking_targets/`
are **not** shipped inside the installer — they're ~101GB and 2.3GB
respectively. The Downloads tab (and, inline, the target pickers on
Predict/Screen/Docking/Target Info) pull only the target buckets a user
actually needs, on demand, from the project's public Cloudflare R2
bucket — baked in as the default in `backend/downloads.py`, so this
works out of the box with zero configuration. See "Data: on-demand
downloads" below only if you need to point a build at a *different*
bucket (a fork, a private staging bucket, etc).

## 1. Install (on the Windows machine, in a venv)
    python -m venv .venv
    .venv\Scripts\activate
    pip install torch --index-url https://download.pytorch.org/whl/cpu
    pip install -r backend\requirements.txt

    cd frontend
    npm install
    npm run build
    cd ..

    # optional, for gold-standard interaction typing (falls back to a
    # built-in distance-based detector if absent — the app still works;
    # see backend/requirements-optional.txt for why this is conda, not pip):
    conda install -c conda-forge plip openbabel

AutoDock Vina is a hard requirement for docking to activate at all —
download the official Windows build and put `vina.exe` on `PATH`, or
drop it in `bin\vina.exe` next to `desktop.py` (desktop.py prepends
`bin\` to `PATH` at startup, see below). fpocket and GNINA have **no
official Windows builds** — both already degrade gracefully (the Docking
tab reports exactly what's missing rather than breaking), so v1 ships
without them on Windows.

## 2. Data: local override paths (optional)
    set TARGETS_DIR=C:\path\to\models              (default: .\models)
    set DOCKING_REGISTRY=C:\path\to\docking_registry.json   (default: .\docking_registry.json)
    set DOCKING_TARGETS_DIR=C:\path\to\docking_targets       (default: .\docking_targets)

`docking_registry.json` (metadata only, ~1.6MB) ships bundled in the
installer. `models/` and `docking_targets/` start out empty and are
populated per-target by the Downloads tab (see below) — these env vars
only matter if you want them somewhere other than next to the exe.

## 3. Data: on-demand downloads (Cloudflare R2)
Defaults to the project's own public bucket
(`https://pub-8ffe9174838b492cab28d50839e49dd7.r2.dev`) — nothing to set
for a normal build. To point at a different bucket instead (a fork, a
private staging copy):

    set DOWNLOAD_BASE_URL=https://<your-bucket-or-cdn>/

(or, for a CI-built installer, set the `DOWNLOAD_BASE_URL` GitHub Actions
repo variable — see `.github/workflows/build-windows.yml` — which is
baked into `installer/PhytoScreen.bat` at build time).

Expected layout at that URL (built once, from the machine that holds the
real 101GB `models/`/2.3GB `docking_targets/`, via
`backend/scripts/build_download_manifest.py`, then uploaded — R2's free
egress makes it the natural choice, but anything serving plain public
HTTPS works, since the installed app never needs credentials):

    manifest.json
    models/<target_id>.zip
    docking_targets/<target_id>.zip

The Downloads tab reads `manifest.json` (via the backend's
`/api/downloads/*` routes, see `backend/downloads.py`) to show what's
available vs. already installed, and extracts each zip into
`TARGETS_DIR/<target_id>/` or `DOCKING_TARGETS_DIR/<target_id>/` on
request, verifying the manifest's sha256 first.

## 4. Run in dev first (confirm it works before packaging)
    python desktop.py
A native PhytoScreen window opens, backed by the built `frontend/dist/`.
If pywebview can't find a usable GUI backend at runtime (rare on real
Windows — it uses the built-in Edge WebView2 backend there) it falls back
to printing a localhost URL to open in a browser instead, rather than
crashing.

Start the ADMET-AI worker separately if you want the learned ADMET layer
(optional; the deterministic layer always works without it):
    uvicorn admet_service:app --app-dir backend --host 127.0.0.1 --port 8100

## 5. Build the .exe (PyInstaller)
From the project root:
    pip install pyinstaller
    pyinstaller --noconfirm --windowed --name PhytoScreen ^
      --paths backend ^
      --add-data "frontend/dist;frontend/dist" ^
      --add-data "docking_registry.json;." ^
      --add-data "panel_results_v2.csv;." ^
      --add-data "models/curated;models/curated" ^
      --add-data "bin;bin" ^
      --collect-all rdkit ^
      --collect-all autogluon ^
      --collect-all chemprop ^
      --collect-all lightning ^
      --collect-all posebusters ^
      --collect-all meeko ^
      --collect-all gemmi ^
      --collect-all webview ^
      --collect-all admet_ai ^
      --collect-all cuik_molmaker ^
      --collect-all openmm ^
      --collect-all pdbfixer ^
      --hidden-import lightgbm ^
      --hidden-import catboost ^
      --hidden-import xgboost ^
      --hidden-import uvicorn ^
      desktop.py
The .exe lands in `dist\PhytoScreen\PhytoScreen.exe` (onedir — not
onefile; deliberately, given how many native extensions are involved).
It creates `models\`/`docking_targets\` next to itself the first time a
download runs; nothing needs to be copied in manually.

A packaged, double-clickable installer (Start Menu/Desktop shortcuts) is
built from this output via Inno Setup — see `installer/phytoscreen.iss`
and `.github/workflows/build-windows.yml`, which runs this whole flow on
a GitHub-hosted Windows runner (PyInstaller does not cross-compile, so
the .exe itself can only be produced by an actual Windows build).

### Why `docking_registry.json`/`panel_results_v2.csv` need explicit env vars in desktop.py, not just `--add-data`
`--add-data "X;."` bundles the file, but doesn't make it resolvable
by a bare relative-path lookup: for a PyInstaller 6.x **onedir** build,
`--add-data` files land in `_internal/` (`sys._MEIPASS`), a *sibling* of
`PhytoScreen.exe`, not the same folder — but `desktop.py` sets the
process's working directory to `os.path.dirname(sys.executable)` (the
*outer* folder, deliberately — that's where `models/`/`docking_targets/`
should land when the Downloads tab creates them, not buried inside
`_internal/`). `backend/docking/profile.py`'s `DOCKING_REGISTRY` and
`backend/scripts/panel_candidates.py`'s `PANEL_RESULTS_CSV` both default
to a bare relative filename resolved against *cwd* — which finds nothing
in the outer folder, silently: no exception, `os.path.exists()` just
returns `False`, so the registry loads as `{}` and the disease/target
panel as empty, rather than erroring. This is why disease search and
target validation showed nothing in a real frozen build — dev-mode
testing never catches it, since there `cwd` already equals the repo
root, exactly where these files really live unfrozen. `desktop.py` now
sets both env vars explicitly to `FROZEN_ROOT` (`sys._MEIPASS`) when
frozen, before `backend/app.py` is ever imported.

### Why `--paths backend`
`desktop.py` imports `backend/app.py` dynamically (`sys.path.insert(0,
BACKEND_DIR); import app`) so it never has to physically move or copy
that file. That trick works at RUN time because desktop.py itself edits
`sys.path` before the import — but PyInstaller decides what to bundle at
BUILD time, from its own static analysis, and has no way to know about a
sys.path edit that only happens once the frozen app is already running.
Without `--paths backend` telling it where to look, PyInstaller can't
resolve `import app` at all, and silently omits backend/app.py and
everything it imports (`serving/`, `analysis.py`, `admet.py`,
`factory_browser.py`, `downloads.py`, `docking/`) from the bundle
entirely — the build still "succeeds" (PyInstaller doesn't hard-fail on
an unresolvable import inside a function body) and produces a
plausible-looking .exe that does nothing when run, since `import app`
raises `ModuleNotFoundError` the moment it actually executes. This
exact failure shipped once — desktop.py's persistent log
(`%LOCALAPPDATA%\PhytoScreen\desktop.log` on Windows) plus a startup
message box exist specifically so it can never fail this silently again.

### Why `--collect-all webview`, not `--hidden-import pywebview`
The PyPI package is named `pywebview`, but the actual importable Python
module is `webview` (`import webview`, as desktop.py does) — pointing
`--hidden-import` at the wrong name (`pywebview`) makes it a silent
no-op. Worse, a plain hidden-import only pulls in `.py` files anyway;
`webview`'s Windows GUI backend ships real binary assets alongside its
code — `WebView2Loader.dll`, `Microsoft.Web.WebView2.*.dll`, and its
JS bridge files — that the native window genuinely can't render without.
`--collect-all webview` (matching the module name, like every other
`--collect-all` entry here — PyInstaller's collect flags key off the
importable name, not the PyPI distribution name; `--collect-all
autogluon` for the `autogluon.tabular` package is the same pattern)
pulls in both the code and those binaries in one go.

### Why `--collect-all cuik_molmaker`
`chemprop`'s own featurizer (`chemprop/featurizers/molgraph/molecule.py`)
imports `cuik_molmaker` — a separate compiled package (a C++ extension
module plus a sibling native library it loads at runtime, plus JSON
normalization data) that neither `--collect-all chemprop` nor plain
import analysis fully captures, since it's not a subpackage of chemprop
and its binary/data files are invisible to static analysis either way.
Missing this doesn't fail the build or even fail `import app` — the
whole ML stack imports fine — it only breaks the instant a REAL
prediction actually runs the Chemprop forward pass, as
`WinError3: The system cannot find the path specified` pointing at
`_internal\cuik_molmake...`. Also breaks the ADMET-AI worker the same
way, less obviously: `admet-ai` is itself built on chemprop
(`admet_ai/admet_model.py` imports directly from `chemprop.models`), so
its model fails to load for the identical reason, silently reported as
just "worker unavailable" rather than this specific error. This is why
Windows CI now actually downloads a real target and runs a real
`/api/predict` call (see the "Verify..." step) instead of only checking
that the app *starts* — a healthy backend and a working prediction are
different guarantees, and this exact bug is what proved it.

### Why `--collect-all openmm`/`--collect-all pdbfixer`
`docking/receptor_prep.py` uses `PDBFixer` (repairing a manually-picked
structure — missing atoms, missing hydrogens) whenever a user selects a
structure OTHER than the pre-baked default (which ships already
prepared, so this code path never runs for it). Both `openmm` and
`pdbfixer` ship real data on disk their code loads at runtime — OpenMM's
forcefield/topology XML files (`openmm/app/data/*.xml`) and PDBFixer's
per-residue template PDBs (`pdbfixer/templates/*.pdb`) — invisible to
plain import analysis the same way `cuik_molmaker`'s files were. Missing
this doesn't break the default docking flow at all (masking it easily)
— only manual structure selection, failing as `[Errno 2] No such file
or directory: '...\_internal\openmm\app\data\...'`.

### Why `--add-data "models/curated;models/curated"`
Fresh/on-demand decoy generation (`backend/scripts/generate_decoys.py`'s
`build_pool()`) reads every OTHER target's curated compounds from
`models/curated/*.csv` to build a property-matched decoy pool — real
source data (~15MB), not something inference-time can compute from
nothing. Unlike `models/<target_id>/` (downloaded on demand from R2 —
see `backend/scripts/build_download_manifest.py`), `models/curated/`
was never part of that manifest at all, so a fresh install has zero
curated CSVs: `build_pool()`'s glob finds nothing, returns an empty
pool, and decoy selection breaks downstream. Small and read-only enough
to just bundle directly into the installer instead of adding it to the
download-on-demand system — `desktop.py` points `CURATED_DATA_DIR` at
`FROZEN_ROOT` when frozen, same pattern as `DOCKING_REGISTRY`/
`PANEL_RESULTS_CSV`.

### Why `--hidden-import lightgbm/catboost/xgboost`
AutoGluon's stacked ensembles are built from these base learners — the
chosen model for several real targets in this repo is `LightGBMXT_BAG_L1`
or a `CatBoost_BAG_*` child. AutoGluon `pickle.load()`s them lazily at
*predict* time, not at `TabularPredictor.load()` time, so a missing base
learner doesn't fail until the first `/api/predict` call against that
specific target — plan for that during testing, don't assume "the app
started fine" means every target works. (This bit development the first
time around: the base venv install had `autogluon.tabular` but not
`lightgbm`, and predictions crashed with `ModuleNotFoundError: No module
named 'lightgbm'` the first time a LightGBM-based target was actually
queried.)

Notes / likely tweaks (validate on your machine):
- PyInstaller sometimes needs extra `--collect-all`/`--hidden-import`
  entries beyond this list; if the .exe reports a missing module at
  launch (or on first predict against a specific target — see above),
  add it and rebuild.
- First launch is slow (unpacking); subsequent launches are fast.
- Loading a target bucket the first time takes ~10s (AutoGluon + the
  Chemprop checkpoint); it's cached in memory afterwards (bounded to
  `PHYTO_MODEL_CACHE_SIZE`, default 2 targets, since buckets can exceed
  500MB each).

## What is tested vs. validate-on-Windows
TESTED (CPU-only Linux venv, real target buckets, real FastAPI
TestClient — see `backend/tests/`): the full predict/admet/docking-
status/screen/factory-browser/downloads API surface, `desktop.py`'s
free-port launch + background server thread + health-check wait +
static-mount ordering (confirmed `/api/health` and `/` both serve from
one process), and pywebview's graceful URL fallback when no GUI backend
loads (verified by literally not having pywebview installed in this
Linux sandbox, which also lacks the GTK/Qt bindings Windows doesn't need
anyway — it uses Edge WebView2).

VALIDATE ON YOUR WINDOWS MACHINE: the actual native window rendering,
the PyInstaller `.exe` packaging itself, a real Vina run (hard
requirement — clear "not ready" status + install checklist in the
Docking tab if missing), and the end-to-end S3 download → extract →
target-appears-in-picker flow against your real bucket.
