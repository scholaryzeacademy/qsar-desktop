# PhytoScreen Desktop (increment 1)

Turns the web serving app into a native Windows desktop app (PyWebview + PyInstaller)
WITHOUT losing any feature, and adds:
  * Models tab data: /api/factory/* browses every per-target factory bucket and
    downloads any file, each annotated, or the whole bucket as a zip.
  * PLIP-based (with fallback) LigPlot+-style 2D interaction diagram for docking.

## New files
  desktop.py                     native-window launcher (starts backend, opens window)
  factory_browser.py             FastAPI router: browse + download factory buckets
  docking/interaction_diagram.py PLIP detection + LigPlot-style 2D diagram

## Wiring (two small edits to existing files)
1. Docking diagram upgrade — in docking/pipeline.py, replace the interaction
   call so it uses the new PLIP+LigPlot renderer:
       from . import interaction_diagram as ID
       inter, source = ID.detect_interactions(profile["receptor_pdb"], best.mol)
       result["interactions"] = inter
       if make_diagram:
           result["interaction_png"] = ID.diagram_png(best.mol, inter,
               title=smiles[:30], source=source,
               ref_residues={h["residue"] for h in (reference_interactions or [])})
   (The old interactions.py stays as the fallback detector.)

2. Models tab — add a "Models" nav button + view to static/index.html that calls
   /api/factory/targets, /api/factory/bucket/{id}, and offers download links to
   /api/factory/download/{id}?path=... and /api/factory/download_all/{id}.
   (Snippet in MODELS_TAB_SNIPPET.html.)

See BUILD_WINDOWS.md for the .exe build.
