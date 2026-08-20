"""
============================================================
  ON-DEMAND TARGET DOWNLOADS  (downloads.py)
============================================================
  Backend endpoints powering the desktop app's Downloads tab: the
  installer ships without models/ (~101GB) or docking_targets/ (~2.3GB)
  — see BUILD_WINDOWS.md — so a user fetches only the target buckets
  they actually need, on demand, from wherever DOWNLOAD_BASE_URL points
  (a public-read S3 bucket or a plain CloudFront distribution in front
  of one; no AWS credentials are ever held by the installed app).

  Expected layout at DOWNLOAD_BASE_URL (built by
  scripts/build_download_manifest.py from a real models/+docking_targets/
  tree, then uploaded — not something this module produces):
      manifest.json
      models/<target_id>.zip
      docking_targets/<target_id>.zip

  manifest.json shape:
      {"targets": {"<target_id>": {
          "qsar_model": {"size": <bytes>, "sha256": "<hex>"} | null,
          "docking":    {"size": <bytes>, "sha256": "<hex>"} | null
      }, ...}}

  DOWNLOAD_BASE_URL unset (the default) disables the feature with a
  clear 503 rather than crashing anything — same "missing optional piece
  degrades, never takes the app down" rule as docking/admet.
============================================================
"""
import os
import time
import uuid
import hashlib
import shutil
import tempfile
import threading
import zipfile

import httpx
from fastapi import APIRouter, HTTPException, Query

from serving import model_adapter as MA
from docking.profile import DOCKING_TARGETS_DIR

router = APIRouter(prefix="/api/downloads", tags=["downloads"])

# The project's own public Cloudflare R2 bucket (see
# backend/scripts/build_download_manifest.py — this is where its output
# gets uploaded) — a zero-config default so a plain install/run just
# works. Override with the DOWNLOAD_BASE_URL env var to point a dev/test
# build at a different bucket (see installer/PhytoScreen.bat, which sets
# it from the DOWNLOAD_BASE_URL GitHub Actions repo variable at build time).
_DEFAULT_DOWNLOAD_BASE_URL = "https://pub-8ffe9174838b492cab28d50839e49dd7.r2.dev"
DOWNLOAD_BASE_URL = os.environ.get("DOWNLOAD_BASE_URL", _DEFAULT_DOWNLOAD_BASE_URL).rstrip("/")
_MANIFEST_TTL = 300  # seconds — short-lived cache, not a hard requirement to be fresh

_manifest_cache = {"data": None, "fetched_at": 0.0}

_jobs_lock = threading.Lock()
_jobs = {}  # job_id -> {"target_id","kind","state","done","total","error"}


def _kind_dir(kind):
    return MA.TARGETS_DIR if kind == "model" else DOCKING_TARGETS_DIR


def _fetch_manifest():
    if not DOWNLOAD_BASE_URL:
        raise HTTPException(503, "DOWNLOAD_BASE_URL is not configured — on-demand downloads are disabled")
    now = time.time()
    if _manifest_cache["data"] is not None and now - _manifest_cache["fetched_at"] < _MANIFEST_TTL:
        return _manifest_cache["data"]
    try:
        r = httpx.get(f"{DOWNLOAD_BASE_URL}/manifest.json", timeout=15)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        if _manifest_cache["data"] is not None:
            return _manifest_cache["data"]  # serve stale rather than fail on a transient S3 hiccup
        raise HTTPException(502, f"could not fetch download manifest: {e}")
    _manifest_cache["data"] = data
    _manifest_cache["fetched_at"] = now
    return data


def _is_installed(target_id, kind):
    """Mirrors the completeness check each consumer already uses, so the
       Downloads tab's 'installed' badge never disagrees with what
       model_adapter/docking actually see."""
    if kind == "model":
        bdir = os.path.join(MA.TARGETS_DIR, target_id)
        needed = ["chosen_model", "selected_features.csv", os.path.join("Data", "fit.csv")]
        return all(os.path.exists(os.path.join(bdir, n)) for n in needed)
    bdir = os.path.join(DOCKING_TARGETS_DIR, target_id)
    return os.path.isdir(bdir) and any(os.scandir(bdir))


@router.get("/status")
def status():
    manifest = _fetch_manifest()
    out = []
    for tid, kinds in sorted((manifest.get("targets") or {}).items()):
        row = {"target_id": tid}
        for manifest_kind, api_kind in (("qsar_model", "model"), ("docking", "docking")):
            info = kinds.get(manifest_kind)
            if info:
                row[api_kind] = {"available": True, "size": info.get("size"),
                                  "installed": _is_installed(tid, api_kind)}
            else:
                row[api_kind] = {"available": False, "installed": False}
        out.append(row)
    return {"download_base_url": DOWNLOAD_BASE_URL, "targets": out}


@router.post("/target/{target_id}")
def start_download(target_id: str, kind: str = Query(..., pattern="^(model|docking)$")):
    manifest = _fetch_manifest()
    manifest_kind = "qsar_model" if kind == "model" else "docking"
    info = (manifest.get("targets", {}).get(target_id) or {}).get(manifest_kind)
    if not info:
        raise HTTPException(404, f"no {kind} bucket published for '{target_id}'")
    if _is_installed(target_id, kind):
        return {"job_id": None, "already_installed": True}

    job_id = uuid.uuid4().hex
    with _jobs_lock:
        _jobs[job_id] = {"target_id": target_id, "kind": kind, "state": "starting",
                          "done": 0, "total": info.get("size") or 0, "error": None}
    threading.Thread(target=_run_download, args=(job_id, target_id, kind, info), daemon=True).start()
    return {"job_id": job_id}


@router.get("/progress/{job_id}")
def progress(job_id: str):
    with _jobs_lock:
        job = _jobs.get(job_id)
    if job is None:
        raise HTTPException(404, "unknown job")
    return job


def _set(job_id, **kw):
    with _jobs_lock:
        _jobs[job_id].update(kw)


def _extract_zip(tmp_zip, target_id, dest_root):
    """Extract into dest_root/<target_id>.tmp/ then atomically rename into
       place, so a reader (model_adapter.list_target_ids(), a concurrent
       downloads/status call) never sees a half-written bucket — same
       atomic-replace discipline as docking/profile.py's registry writes.
       Zip members are stored as '<target_id>/<relpath>' (mirroring
       factory_browser.download_all's own convention); the leading
       component is stripped and anything that would escape the
       destination directory is rejected (path traversal)."""
    final_dir = os.path.join(dest_root, target_id)
    tmp_dir = final_dir + ".tmp"
    if os.path.isdir(tmp_dir):
        shutil.rmtree(tmp_dir)
    os.makedirs(tmp_dir, exist_ok=True)
    abs_tmp_dir = os.path.abspath(tmp_dir)
    with zipfile.ZipFile(tmp_zip) as z:
        for member in z.infolist():
            parts = member.filename.split("/", 1)
            relpath = parts[1] if len(parts) == 2 else parts[0]
            if not relpath or relpath.startswith("..") or os.path.isabs(relpath):
                continue
            dest = os.path.abspath(os.path.join(abs_tmp_dir, relpath))
            if not (dest == abs_tmp_dir or dest.startswith(abs_tmp_dir + os.sep)):
                continue
            if member.is_dir():
                os.makedirs(dest, exist_ok=True)
                continue
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with z.open(member) as src, open(dest, "wb") as out:
                shutil.copyfileobj(src, out)
    if os.path.isdir(final_dir):
        shutil.rmtree(final_dir)
    os.replace(tmp_dir, final_dir)


def _run_download(job_id, target_id, kind, info):
    dest_root = _kind_dir(kind)
    remote_dir = "models" if kind == "model" else "docking_targets"
    zip_url = f"{DOWNLOAD_BASE_URL}/{remote_dir}/{target_id}.zip"
    tmp_zip = None
    try:
        os.makedirs(dest_root, exist_ok=True)
        fd, tmp_zip = tempfile.mkstemp(prefix=f"{target_id}.", suffix=".zip.part", dir=dest_root)
        os.close(fd)

        _set(job_id, state="downloading")
        sha256 = hashlib.sha256()
        with httpx.stream("GET", zip_url, timeout=60) as r:
            r.raise_for_status()
            total = int(r.headers.get("content-length") or info.get("size") or 0)
            _set(job_id, total=total)
            done = 0
            with open(tmp_zip, "wb") as f:
                for chunk in r.iter_bytes(chunk_size=1024 * 1024):
                    f.write(chunk)
                    sha256.update(chunk)
                    done += len(chunk)
                    _set(job_id, done=done)

        expected = info.get("sha256")
        if expected and sha256.hexdigest() != expected:
            raise ValueError(f"checksum mismatch downloading {target_id} ({kind})")

        _set(job_id, state="extracting")
        _extract_zip(tmp_zip, target_id, dest_root)
        _set(job_id, state="done")
    except Exception as e:
        _set(job_id, state="error", error=str(e))
    finally:
        if tmp_zip and os.path.exists(tmp_zip):
            os.remove(tmp_zip)
