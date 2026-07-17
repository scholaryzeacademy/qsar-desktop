# PhytoScreen Desktop — Windows build (.exe)

The desktop app reuses your EXISTING serving app unchanged (Predict / ADMET /
Compare / Docking + validation panels) inside a native window, and adds a
Models tab that browses the factory's per-target buckets.

## Files (put these in your qasr_2 serving-app folder)
    desktop.py                       # the native-window launcher
    factory_browser.py               # /api/factory/* endpoints (browse+download buckets)
    docking/interaction_diagram.py   # PLIP detection + LigPlot-style 2D diagram
    app.py, static/, docking/, admet*.py, serve.py, pipeline.py, registry.json, ...  (existing)

## 1. Install (on the Windows machine, in your venv)
    pip install pywebview pyinstaller
    # optional, for the true-quality interaction detection:
    conda install -c conda-forge plip openbabel        # PLIP needs OpenBabel
    # everything else (rdkit, fastapi, uvicorn, meeko, posebusters, vina...) as before

## 2. Run in dev first (confirm it works before packaging)
    python desktop.py
A native PhytoScreen window opens. If pywebview's backend is missing, it prints
a localhost URL you can open in a browser instead.

Point it at your factory output so the Models tab sees the buckets:
    set FACTORY_OUTPUT=C:\path\to\factory_output      (Windows)
    export FACTORY_OUTPUT=/path/to/factory_output     (Linux/Mac dev)

## 3. Build the .exe (PyInstaller)
From the serving-app folder:
    pyinstaller --noconfirm --windowed --name PhytoScreen ^
      --add-data "static;static" ^
      --add-data "docking;docking" ^
      --add-data "diseases.yaml;." ^
      --add-data "registry.json;." ^
      --collect-all rdkit ^
      --collect-all posebusters ^
      --collect-all meeko ^
      --hidden-import uvicorn ^
      desktop.py
The .exe lands in  dist\PhytoScreen\PhytoScreen.exe

Notes / likely tweaks (validate on your machine):
- RDKit/scikit-learn/xgboost sometimes need extra --collect-all or --hidden-import
  entries; add them if the .exe reports a missing module at launch.
- The ADMET-AI worker (admet_service.py) stays a SEPARATE process; start it as
  before. The app talks to it over the local URL; if it's off, ADMET falls back
  to the deterministic layer exactly as in the web app.
- Vina / (optional) GNINA / PLIP are external binaries; they are NOT bundled —
  install them on the machine and keep them on PATH, same as the web app.
- First launch is slow (unpacking); subsequent launches are fast.

## What is tested vs validate-on-Windows
TESTED (on Linux, backend logic): the free-port launch, background server thread,
health, the factory bucket browser (list targets, list files with annotations,
download a file, download the whole bucket as a zip, path-traversal blocked),
and the LigPlot-style 2D diagram renderer (all interaction types).
VALIDATE ON YOUR MACHINE: the actual native window (pywebview needs a display),
the PyInstaller .exe packaging, and the real PLIP run (needs PLIP+OpenBabel).
PLIP detection has a graceful fallback to the built-in distance-based detector,
so the diagram works even without PLIP.
