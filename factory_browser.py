"""
============================================================
  FACTORY BUCKET BROWSER  (factory_browser.py)
============================================================
  Backend endpoints that let the desktop app browse every per-target
  output bucket produced by the model factory and download any file
  (plots, xlsx, csv, model, report) — each annotated with what it is.

  Point FACTORY_OUTPUT at the factory's output_root (default ./factory_output).
  Mount this router onto the main FastAPI app.
============================================================
"""
import os, mimetypes
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

FACTORY_OUTPUT = os.environ.get("FACTORY_OUTPUT", "factory_output")

router = APIRouter(prefix="/api/factory", tags=["factory"])

# human-readable annotation for each known file (so the UI can label downloads)
FILE_ANNOTATIONS = {
    "model/best_model.joblib": "Trained best model (with feature list + applicability-domain parameters)",
    "model/hyperparameters.json": "Tuned hyper-parameters of the best model",
    "model/selected_features.csv": "Selected feature list (order matters for prediction)",
    "results/metrics.xlsx": "Headline performance metrics of the best model",
    "results/model_leaderboard.xlsx": "All base models compared (cross-validated + test)",
    "results/test_predictions.xlsx": "Actual vs predicted for the held-out test set (+ residuals, in/out of domain)",
    "results/validation_summary.xlsx": "Y-randomization, Tropsha criteria, applicability-domain checks",
    "data/train_data.csv": "Training compounds used to fit the model",
    "data/test_data.csv": "Held-out test compounds",
    "data/split_assignments.csv": "Scaffold and train/test assignment for every compound",
    "plots/actual_vs_predicted.png": "Actual vs predicted scatter (test set)",
    "plots/model_comparison.png": "Cross-validated R² of every base model (best highlighted)",
    "plots/residuals.png": "Residual plot (test set)",
    "plots/y_randomization.png": "Y-randomization distribution vs the real model",
    "plots/applicability_domain.png": "Applicability-domain coverage of the test set",
    "plots/feature_importance.png": "Top-20 most important features",
    "REPORT.md": "Publication-ready methods & results write-up",
    "README.txt": "What this bucket contains",
}


def _bucket_root():
    return os.path.abspath(FACTORY_OUTPUT)


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
        return {"output_root": root, "targets": []}
    out = []
    for tid in sorted(os.listdir(root)):
        bdir = os.path.join(root, tid)
        if not os.path.isdir(bdir) or tid.startswith("_") or tid.startswith("ALL_TARGETS"):
            continue
        metrics = {}
        mx = os.path.join(bdir, "results", "metrics.xlsx")
        if os.path.exists(mx):
            try:
                import pandas as pd
                metrics = pd.read_excel(mx).iloc[0].to_dict()
            except Exception:
                pass
        out.append({"target_id": tid,
                    "has_model": os.path.exists(os.path.join(bdir, "model", "best_model.joblib")),
                    "best_model": metrics.get("Model"),
                    "test_R2": metrics.get("R2"), "spearman": metrics.get("Spearman"),
                    "ad_coverage_pct": metrics.get("AD_Coverage_pct"),
                    "tropsha_pass": bool(metrics.get("Tropsha_Pass")) if "Tropsha_Pass" in metrics else None})
    return {"output_root": root, "targets": out}


@router.get("/bucket/{target_id}")
def list_bucket(target_id: str):
    bdir = os.path.join(_bucket_root(), target_id)
    if not os.path.isdir(bdir):
        raise HTTPException(404, f"no bucket for '{target_id}'")
    files = []
    for dirpath, _, names in os.walk(bdir):
        if os.path.basename(dirpath) == "_cache":
            continue
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
