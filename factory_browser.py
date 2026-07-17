"""
============================================================
  TARGET BUCKET BROWSER  (factory_browser.py)
============================================================
  Backend endpoints powering the "Target Info" tab (CLAUDE.md §7.5):
  browse every per-target bucket produced by the model factory, show
  headline QSAR metrics + docking validation, and download any file
  (plots, xlsx, csv, model, report) — each annotated — or the whole
  bucket as a zip. This IS the "make the rigor visible" requirement:
  the university must be able to see and download everything.

  Points at TARGETS_DIR (same env var as serving/model_adapter.py,
  default ./models) — the real bucket layout, not a hypothetical one.
============================================================
"""
import os, mimetypes
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from serving import model_adapter as MA

router = APIRouter(prefix="/api/factory", tags=["factory"])

# human-readable annotation for each known file (path relative to the
# target's bucket root), so the UI can label downloads meaningfully.
FILE_ANNOTATIONS = {
    "chosen_model/predictor.pkl": "The trained AutoGluon predictor (stacked ensemble)",
    "chosen_model/learner.pkl": "AutoGluon learner (preprocessing + label metadata)",
    "chosen_model/version.txt": "AutoGluon version used to train this model",
    "chosen_model/metadata.json": "Training environment (package versions, OS)",
    "selected_features.csv": "Selected feature list, in order — required to featurise new molecules correctly",
    "metrics.xlsx": "Headline performance metrics of the shipped model",
    "model_leaderboard.xlsx": "All AutoGluon base models compared (cross-validated + test)",
    "test_predictions.xlsx": "Actual vs predicted for the held-out test set (+ residuals)",
    "oof_predictions.xlsx": "Out-of-fold cross-validated predictions",
    "feature_importance.xlsx": "Feature importance ranking",
    "config_used.yaml": "Exact configuration used for this training run",
    "run_metadata.json": "Full run metadata: metrics, Tropsha detail, split counts, timestamp",
    "run_log.txt": "Raw training log",
    "_DONE.json": "Marks this target's pipeline run as complete",
    "Data/fit.csv": "Training feature matrix used to fit the shipped model",
    "Data/test.csv": "Held-out test feature matrix",
    "Data/full_cleaned.csv": "Full curated dataset before the fit/test split",
    "Plots/01_Actual_vs_Predicted.png": "Actual vs predicted scatter (test set)",
    "Plots/02_Residuals_vs_Predicted.png": "Residuals vs predicted (test set)",
    "Plots/03_Residual_Distribution.png": "Residual distribution",
    "Plots/04_Residual_QQ.png": "Residual Q-Q plot",
    "Plots/05_Model_Comparison.png": "Cross-validated performance of every base model",
    "Plots/06_Y_Randomization.png": "Y-randomisation distribution vs the real model",
    "Plots/07_Feature_Importance.png": "Top features by importance",
    "Plots/08_Applicability_Domain.png": "Applicability-domain coverage of the test set",
    "Plots/09_Target_Distribution.png": "Distribution of the training activity values",
}


def _bucket_root():
    return os.path.abspath(MA.TARGETS_DIR)


def _safe(target_id, relpath):
    """Resolve a file path inside a bucket, blocking path traversal."""
    root = _bucket_root()
    full = os.path.abspath(os.path.join(root, target_id, relpath))
    if not full.startswith(os.path.join(root, target_id) + os.sep) and full != os.path.join(root, target_id):
        raise HTTPException(400, "invalid path")
    return full


@router.get("/targets")
def list_targets():
    root = _bucket_root()
    if not os.path.isdir(root):
        return {"targets_dir": root, "targets": []}
    out = []
    for meta in MA.list_targets_meta():
        m = meta["metrics"]
        out.append({
            "target_id": meta["target_id"],
            "has_model": os.path.exists(os.path.join(root, meta["target_id"], "chosen_model", "predictor.pkl")),
            "best_model": m.get("Best_Model") or m.get("best_model"),
            "test_r2": m.get("R2_Test"), "pearson_r": m.get("Pearson_r"), "test_rmse": m.get("RMSE_Test"),
            "ad_coverage_pct": m.get("AD_Coverage_pct"),
            "tropsha_pass": m.get("Tropsha_Pass") if "Tropsha_Pass" in m else None,
            "has_metrics": bool(m),
        })
    return {"targets_dir": root, "targets": out}


@router.get("/target/{target_id}/metrics")
def target_metrics(target_id: str):
    bdir = os.path.join(_bucket_root(), target_id)
    if not os.path.isdir(bdir):
        raise HTTPException(404, f"no bucket for '{target_id}'")
    return {"target_id": target_id, "metrics": MA.get_metrics(target_id)}


@router.get("/bucket/{target_id}")
def list_bucket(target_id: str):
    bdir = os.path.join(_bucket_root(), target_id)
    if not os.path.isdir(bdir):
        raise HTTPException(404, f"no bucket for '{target_id}'")
    files = []
    for dirpath, _, names in os.walk(bdir):
        if os.path.basename(dirpath) == "_cache":
            continue   # internal cache (chemprop checkpoint + raw preds), not a deliverable
        for n in sorted(names):
            full = os.path.join(dirpath, n)
            rel = os.path.relpath(full, bdir).replace(os.sep, "/")
            files.append({"path": rel, "name": n, "bytes": os.path.getsize(full),
                          "annotation": FILE_ANNOTATIONS.get(rel, ""),
                          "category": rel.split("/")[0] if "/" in rel else "root"})
    files.sort(key=lambda f: (f["category"], f["path"]))
    return {"target_id": target_id, "n_files": len(files), "files": files}


@router.get("/download/{target_id}")
def download(target_id: str, path: str):
    full = _safe(target_id, path)
    if not os.path.isfile(full):
        raise HTTPException(404, "file not found")
    mt = mimetypes.guess_type(full)[0] or "application/octet-stream"
    return FileResponse(full, media_type=mt, filename=os.path.basename(full))


@router.get("/download_all/{target_id}")
def download_all(target_id: str):
    """Zip the whole target bucket (minus _cache) for one-click 'download everything'."""
    import io, zipfile
    from fastapi.responses import StreamingResponse
    bdir = os.path.join(_bucket_root(), target_id)
    if not os.path.isdir(bdir):
        raise HTTPException(404, f"no bucket for '{target_id}'")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for dirpath, _, names in os.walk(bdir):
            if os.path.basename(dirpath) == "_cache":
                continue
            for n in names:
                full = os.path.join(dirpath, n)
                arc = os.path.join(target_id, os.path.relpath(full, bdir))
                z.write(full, arc)
    buf.seek(0)
    return StreamingResponse(buf, media_type="application/zip",
                             headers={"Content-Disposition": f'attachment; filename="{target_id}_bucket.zip"'})
