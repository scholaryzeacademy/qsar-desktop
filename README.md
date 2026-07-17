# PhytoScreen Desktop

A local, offline, CPU-only desktop app for prioritising compounds against a
validated biological target — QSAR potency (Chemprop + AutoGluon), ADMET
profiling, and structure-based docking, wrapped in a native window
(PyWebview + PyInstaller). See `CLAUDE.md` for the full spec.

## Layout

    desktop.py              native-window launcher (starts backend, opens window)
    app.py                  FastAPI backend — mounts predict/admet/docking/screen
                             + the factory_browser router (Target Info tab)
    serving/                the only code that knows the model-bucket format
      model_adapter.py        loads a target bucket (AutoGluon + Chemprop), predicts
      featurize.py             SMILES -> the exact training feature space
      applicability.py         AD z-score gating
      confidence.py            honest confidence tiers (target test RMSE, not a
                                fabricated per-compound interval)
      screen.py                the STEP 1-8 Screen pipeline orchestration
    analysis.py              multi-target / disease comparison
    admet.py / admet_service.py / admet_endpoints.py   ADMET deterministic
                             layer + isolated ADMET-AI worker process
    factory_browser.py      /api/factory/* — browse + download every file in
                             a target's bucket (Target Info tab)
    docking/                 receptor prep, ligand prep, Vina engine, PoseBusters
                             gate, pose consensus, RMSD, PLIP+LigPlot-style 2D
                             interaction diagrams (falls back to a built-in
                             distance-based detector if PLIP isn't installed)
    static/index.html        single-page UI: Screen / Predict / ADMET / Compare
                             / Docking / Target Info
    models/<target_id>/      per-target buckets (read-only input; see CLAUDE.md §5)
    docking_targets/<id>/    prepared receptors (read-only input)
    docking_registry.json    docking targets + validation (portable relative paths)

Run in dev: `python desktop.py`. See `BUILD_WINDOWS.md` for the `.exe` build.
