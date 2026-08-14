"""Batch-run 'Find best validated structure automatically' (see app.py's
/api/docking/receptor/auto_validate) for EVERY protein target in
panel_results_v2.csv that has no QSAR model — the GENE_<symbol> targets the
UI previously always required a manual Advanced Settings structure pick for.

Reuses scripts/batch_validate.py's run_one() unchanged (candidate ranking,
redocking, accept-or-revert) — this script's only job is building the
GENE_<symbol> id list and running many of them CONCURRENTLY via a thread
pool, since each run_one() call is I/O/subprocess-bound (network fetches +
Vina/PDBFixer subprocesses), not CPU-bound in THIS process. Safe to run
concurrently now that docking/profile.py's registry_lock() + atomic
write_registry_json() protect docking_registry.json from concurrent writers
— see those docstrings for exactly what they protect against.

Resumable: already-validated targets are skipped (skip_validated=True), so
a killed/restarted run just picks up where it left off — same as scripts/
backfill_enrichment_references.py's pattern.

Usage:
    python -m scripts.auto_validate_all_genes [--workers N] [--limit N]
"""
import argparse
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd

from scripts import batch_validate as BV
from scripts.panel_candidates import PANEL_CSV


def gene_only_target_ids():
    """Every GENE_<symbol> id the app itself would construct for a no-QSAR-
       model target (see static/index.html's populateGroupTargets) — every
       panel CSV gene EXCEPT the ones covered by a real QSAR target_id."""
    df = pd.read_csv(PANEL_CSV)
    all_genes = sorted(df["targetSymbol"].unique())
    modeled_genes = {BV.gene_for_target(t) for t in BV.usable_targets()}
    return [f"GENE_{g}" for g in all_genes if g not in modeled_genes]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--limit", type=int, default=None, help="process only the first N (for a sample run)")
    args = ap.parse_args()

    targets = gene_only_target_ids()
    if args.limit:
        targets = targets[:args.limit]
    print(f"{len(targets)} no-QSAR-model targets, {args.workers} workers", flush=True)

    done = failed = skipped = 0
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(BV.run_one, tid, True): tid for tid in targets}
        for i, fut in enumerate(as_completed(futures), 1):
            tid = futures[fut]
            try:
                fut.result()
                entry = BV.registry_entry(tid)
                if entry and entry.get("validated"):
                    done += 1
                    print(f"[{i}/{len(targets)}] {tid}: VALIDATED ({entry.get('pdb_source')}, "
                          f"RMSD {entry.get('reference_rmsd')} Å) — elapsed {time.time()-t0:.0f}s total", flush=True)
                else:
                    skipped += 1
                    print(f"[{i}/{len(targets)}] {tid}: no candidate validated", flush=True)
            except Exception as e:
                failed += 1
                print(f"[{i}/{len(targets)}] {tid}: FAILED - {e}", flush=True)

    print(f"\n=== auto_validate_all_genes complete: {done} validated, {skipped} no candidate passed, "
          f"{failed} errored, {time.time()-t0:.0f}s total ===", flush=True)


if __name__ == "__main__":
    main()
