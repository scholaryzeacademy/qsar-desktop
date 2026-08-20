"""
Build the S3 upload set for the desktop app's on-demand Downloads tab
(see BUILD_WINDOWS.md, downloads.py).

Run from the repo root, on the machine that holds the REAL models/ and
docking_targets/ trees (not the installed desktop app — this script is
never shipped/frozen, it's a one-off publishing step):

    python backend/scripts/build_download_manifest.py --out-dir _download_staging

Produces:
    _download_staging/manifest.json
    _download_staging/models/<target_id>.zip           (one per QSAR-modeled target)
    _download_staging/docking_targets/<target_id>.zip   (one per docking target)

Each zip stores members as "<target_id>/<relpath>" — the same convention
factory_browser.download_all() already uses, and what downloads.py's
extractor expects (it strips that leading component on extract).

Upload the result yourself, e.g.:
    aws s3 sync _download_staging/ s3://your-bucket/ --acl public-read
(or point a CloudFront distribution at a private bucket instead of using
--acl public-read — either way, DOWNLOAD_BASE_URL on the desktop app just
needs to be a plain HTTPS URL that GETs these files with no auth, since
the installed app never holds AWS credentials.)

--targets restricts to specific target_ids (handy for republishing after
one target's data changes, without re-zipping everything). --skip-existing
skips a target if its zip already exists in --out-dir (fast incremental
re-runs after adding a few new targets).
"""
import argparse
import hashlib
import json
import os
import sys
import zipfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from serving import model_adapter as MA
from docking.profile import DOCKING_TARGETS_DIR


def _sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _zip_bucket(target_id, bucket_dir, out_path, skip_dirnames=()):
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as z:
        for dirpath, dirnames, names in os.walk(bucket_dir):
            dirnames[:] = [d for d in dirnames if d not in skip_dirnames]
            for n in names:
                full = os.path.join(dirpath, n)
                arc = os.path.join(target_id, os.path.relpath(full, bucket_dir))
                z.write(full, arc)


def _docking_target_ids():
    """docking_targets/<id>/ dirs that look like real prepared receptors
       (at least one file) — mirrors models/'s own '_'-prefixed-dirs-are-
       not-targets convention (e.g. models/_SUMMARY) since docking_targets/
       has the same pattern (docking_targets/_custom)."""
    if not os.path.isdir(DOCKING_TARGETS_DIR):
        return []
    out = []
    for name in sorted(os.listdir(DOCKING_TARGETS_DIR)):
        if name.startswith("_"):
            continue
        bdir = os.path.join(DOCKING_TARGETS_DIR, name)
        if os.path.isdir(bdir) and any(os.scandir(bdir)):
            out.append(name)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out-dir", default="_download_staging")
    ap.add_argument("--targets", nargs="*", default=None, help="restrict to these target_ids (default: all)")
    ap.add_argument("--skip-existing", action="store_true", help="skip a target if its zip already exists")
    args = ap.parse_args()

    model_ids = set(MA.list_target_ids())
    docking_ids = set(_docking_target_ids())
    all_ids = sorted(model_ids | docking_ids)
    if args.targets:
        wanted = set(args.targets)
        all_ids = [t for t in all_ids if t in wanted]
        model_ids &= wanted
        docking_ids &= wanted

    manifest = {"targets": {}}
    manifest_path = os.path.join(args.out_dir, "manifest.json")
    os.makedirs(args.out_dir, exist_ok=True)
    if os.path.exists(manifest_path):
        with open(manifest_path) as f:
            manifest = json.load(f)

    def _save_manifest():
        # Written after every target (atomic replace, like docking/profile.py's
        # registry writes) rather than once at the end — this run is against
        # ~103GB of real data over many hours, and a crash/interrupt partway
        # through must not throw away every zip already built + hashed before
        # it. Resuming with --skip-existing then only needs to re-hash
        # already-built zips, not re-zip them.
        tmp = manifest_path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(manifest, f, indent=2)
        os.replace(tmp, manifest_path)

    failed = []
    for i, tid in enumerate(all_ids, 1):
        print(f"[{i}/{len(all_ids)}] {tid}", flush=True)
        entry = manifest["targets"].setdefault(tid, {"qsar_model": None, "docking": None})

        try:
            if tid in model_ids:
                out_path = os.path.join(args.out_dir, "models", f"{tid}.zip")
                if not (args.skip_existing and os.path.exists(out_path)):
                    # Unlike factory_browser.download_all() (which skips
                    # _cache/ as "not a deliverable" for a human Browse/
                    # download), this zip must be functionally complete —
                    # model_adapter.Target.__init__ hard-requires
                    # _cache/chemprop_final.ckpt and raises BucketError
                    # without it, so a downloaded bucket missing it would
                    # look "installed" (list_target_ids() doesn't check for
                    # it either) but crash the first time anyone predicts
                    # against it. _cache/ is tiny (a few MB) next to
                    # chosen_model/, so there's no real size cost either way.
                    _zip_bucket(tid, os.path.join(MA.TARGETS_DIR, tid), out_path)
                entry["qsar_model"] = {"size": os.path.getsize(out_path), "sha256": _sha256_of(out_path)}

            if tid in docking_ids:
                out_path = os.path.join(args.out_dir, "docking_targets", f"{tid}.zip")
                if not (args.skip_existing and os.path.exists(out_path)):
                    _zip_bucket(tid, os.path.join(DOCKING_TARGETS_DIR, tid), out_path)
                entry["docking"] = {"size": os.path.getsize(out_path), "sha256": _sha256_of(out_path)}
        except Exception as e:
            # One bad bucket (disk full, a mid-read file-permission hiccup)
            # shouldn't take down a multi-hour run for every other target —
            # note it and keep going; _save_manifest() below still reflects
            # every target that DID succeed so far.
            print(f"  FAILED: {e}", flush=True)
            failed.append((tid, str(e)))
        finally:
            _save_manifest()

    print(f"\nWrote {manifest_path} ({len(manifest['targets'])} targets total).")
    if failed:
        print(f"{len(failed)} target(s) FAILED (re-run with --targets to retry just these):")
        for tid, err in failed:
            print(f"  {tid}: {err}")
    print(f"Upload with e.g.: aws s3 sync {args.out_dir}/ s3://your-bucket/ --acl public-read")


if __name__ == "__main__":
    main()
