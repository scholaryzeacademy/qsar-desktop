"""One-off batch backfill: save an enrichment_reference.json (per-compound
active/decoy scores, not just the aggregate AUC/EF already in
docking_registry.json) for every already-validated target that doesn't have
one yet — see docking/enrichment.py and scripts/enrichment_test.py.save_reference.

Re-runs each target's enrichment set with build_enrichment_rows_property_matched
(same n_side=8 default validate_target.py used originally — confirmed against
the registry: every validated target's enrichment_n is ~24, i.e. n_side=8),
docks it, and persists the full per-compound ranking. Registry fields
(validated/reference_rmsd/enrichment_auc/etc.) are NEVER touched here — this
only ever writes docking_targets/<target_id>/enrichment_reference.json.

Resumable: skips any target that already has a reference file, so a killed/
restarted run just picks up where it left off. Per-target failures are caught
and logged, not fatal to the batch.

Usage: python -m scripts.backfill_enrichment_references
"""
import json
import sys
import time

from docking.profile import REGISTRY
from docking.enrichment import reference_path
from scripts.validate_target import build_enrichment_rows_property_matched
from scripts.enrichment_test import dock_scores, metrics, save_reference


def main():
    reg = json.load(open(REGISTRY))
    validated = [t for t in reg["targets"] if t.get("validated")]
    print(f"{len(validated)} validated targets", flush=True)

    done, skipped, failed = [], [], []
    for i, t in enumerate(validated, 1):
        tid = t["target_id"]
        import os
        if os.path.exists(reference_path(tid)):
            print(f"[{i}/{len(validated)}] {tid}: already has a reference, skipping", flush=True)
            skipped.append(tid)
            continue
        print(f"[{i}/{len(validated)}] {tid}: docking enrichment set...", flush=True)
        t0 = time.time()
        try:
            rows = build_enrichment_rows_property_matched(tid, 8)
            scored = dock_scores(tid, rows)
            m = metrics(scored)
            path = save_reference(tid, m, pdb_source=t.get("pdb_source"), decoy_method="property_matched",
                                  source_note=t.get("enrichment_source") or "property_matched decoys (see scripts/generate_decoys.py)")
            dt = time.time() - t0
            print(f"[{i}/{len(validated)}] {tid}: DONE in {dt:.0f}s "
                  f"(AUC {m.get('auc')}, was {t.get('enrichment_auc')} at validation) -> {path}", flush=True)
            done.append(tid)
        except Exception as e:
            print(f"[{i}/{len(validated)}] {tid}: FAILED - {e}", flush=True)
            failed.append((tid, str(e)))

    print(f"\n=== backfill complete: {len(done)} done, {len(skipped)} already had one, {len(failed)} failed ===", flush=True)
    if failed:
        for tid, err in failed:
            print(f"  FAILED {tid}: {err}", flush=True)


if __name__ == "__main__":
    main()
