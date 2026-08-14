"""
Per-compound comparison against a target's known active/decoy distribution.
[orchestration WRITTEN; docking runs UNVALIDATED — same status as the rest
of this package's subprocess-backed code]

Two tiers, matching what's actually useful at different points in a workflow:

  - annotate_with_reference(): FREE. Every docked compound gets ranked
    against the target's ALREADY-SAVED active/decoy distribution (written by
    scripts/validate_target.py's redocking-gated enrichment step; see
    scripts/enrichment_test.py.save_reference) — no extra docking, instant,
    standardized screening evidence for every submission.

  - fresh_decoy_validation(): EXPENSIVE (~50 extra Vina runs). For one
    compound worth deeper scrutiny (a shortlisted hit), generates NEW decoys
    property-matched + topologically-dissimilar to THAT SPECIFIC compound
    (reusing scripts/generate_decoys.py's exact DUD-E-style selection
    against a single-molecule query instead of the target's original
    actives) and docks all of them with the same receptor/box/engine, so the
    percentile reflects this molecule's own chemical neighborhood rather
    than the original validation actives'.

Both stay silent/no-op (never invented) when the comparison wouldn't be
apples-to-apples: a manually-picked Advanced Settings structure (never
'validated' by construction — see docking/receptor_prep.py), blind docking
(different box than the reference was built against), or a target that
simply hasn't been through scripts/validate_target.py's enrichment step yet.
"""
import json
import os

from .profile import DOCKING_TARGETS_DIR


def reference_path(target_id):
    return os.path.join(DOCKING_TARGETS_DIR, target_id, "enrichment_reference.json")


def load_reference(target_id):
    path = reference_path(target_id)
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return json.load(f)


def percentile_rank(score, reference_scores):
    """% of reference_scores this score beats. Lower Vina score = better
       binding, so 'beats' means strictly lower; ties count as half-beaten
       (standard percentile-of-score convention)."""
    if not reference_scores:
        return None
    worse = sum(1 for s in reference_scores if s > score)
    tied = sum(1 for s in reference_scores if s == score)
    return round(100.0 * (worse + 0.5 * tied) / len(reference_scores), 1)


def discrimination_label(percentile):
    if percentile is None:
        return None
    if percentile >= 90:
        return "Strong"
    if percentile >= 65:
        return "Moderate"
    return "Weak"


def annotate_with_reference(result, target_id, profile):
    """Attaches enrichment_percentile/enrichment_context to a dock_compound()
       result IN PLACE (also returned for convenience). No-ops when:
         - the compound itself has no valid pose/score
         - profile isn't validated (True for EVERY Advanced Settings custom
           structure, by construction, so this also excludes those with no
           extra bookkeeping)
         - blind docking mode (different box than the reference)
         - no reference saved yet, or it was built against a different PDB
           than the target's CURRENT registry structure (stale after a
           re-validation onto a new structure)
    """
    score = result.get("vina_score")
    if score is None:
        return result
    if not profile.get("validated") or profile.get("site_source") == "blind_whole_protein":
        return result
    ref = load_reference(target_id)
    if not ref or ref.get("pdb_source") != profile.get("pdb_source"):
        return result
    scores = [c["score"] for c in ref["compounds"] if c.get("score") is not None]
    if not scores:
        return result
    actives = [c for c in ref["compounds"] if c["label"] == "active" and c.get("score") is not None]
    best_active = min((c["score"] for c in actives), default=None)
    result["enrichment_percentile"] = percentile_rank(score, scores)
    result["enrichment_context"] = {
        "n_reference": len(scores), "n_active": len(actives), "n_decoy": len(scores) - len(actives),
        "best_known_active_score": best_active,
        "beats_best_known_active": (best_active is not None and score <= best_active),
        "decoy_method": ref.get("decoy_method"),
    }
    return result


def fresh_decoy_validation(target_id, smiles, profile, engine=None, n_decoys=50, seed=None, progress_cb=None):
    """~(n_decoys + 1) Vina runs. Returns a dict with compound_score,
       percentile, discrimination label, and the per-decoy scores — or
       {'error': ...} if the compound/pool can't support the test.

       Decoys are docked CONCURRENTLY (a thread pool, one Vina subprocess
       per worker) — sequentially this was ~50 back-to-back Vina calls,
       10+ minutes wall-clock with 31 of 32 cores sitting idle the whole
       time, since a single exhaustiveness=8 Vina run only keeps ~8 cores
       busy. Workers get an explicit --cpu cap (docking/engines.py) so N
       concurrent Vina processes divide the machine's cores instead of each
       one independently grabbing all of them and thrashing.

       progress_cb(done, total), if given, is called after every dock
       (compound first, then each decoy as its own thread finishes) so a
       caller can show live progress instead of one static "generating..."
       message for the whole run — the single biggest reason this used to
       look hung: no visible movement for many minutes."""
    import os
    import pandas as pd
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from .pipeline import dock_compound
    from .engines import VinaEngine, NullRescorer
    from scripts.generate_decoys import build_pool, select_decoys

    engine = engine or VinaEngine()
    pool = build_pool(exclude_target_id=target_id)
    actives_df = pd.DataFrame([{"smiles": smiles}])
    decoys = select_decoys(actives_df, pool, n_per_active=n_decoys, seed=seed if seed is not None else 42)
    if not decoys:
        return {"error": "No property-matched, topologically-dissimilar decoys found for this "
                         "compound in the candidate pool (models/curated/*.csv) — it may be "
                         "structurally unusual relative to every other target's curated compounds."}

    total = len(decoys) + 1
    done = 0
    if progress_cb:
        progress_cb(done, total)

    compound_res = dock_compound(profile, smiles, engine=engine, rescorer=NullRescorer())
    compound_pose = compound_res.get("consensus_pose")
    compound_score = compound_pose["score"] if compound_pose else None
    done += 1
    if progress_cb:
        progress_cb(done, total)
    if compound_score is None:
        return {"error": "This compound did not produce a valid (PoseBusters-passing) pose against "
                         "this receptor — nothing to rank against decoys."}

    n_workers = min(8, max(1, os.cpu_count() or 4))
    cpu_per_worker = max(1, (os.cpu_count() or n_workers) // n_workers)

    def _dock_one(d):
        worker_engine = VinaEngine(binary=engine.binary, exhaustiveness=engine.exhaustiveness, cpu=cpu_per_worker)
        r = dock_compound(profile, d["smiles"], engine=worker_engine, rescorer=NullRescorer())
        pose = r.get("consensus_pose")
        return {"name": d["name"], "smiles": d["smiles"], "source_target": d.get("source_target"),
               "score": pose["score"] if pose else None}

    decoy_rows = []
    with ThreadPoolExecutor(max_workers=n_workers) as pool_exec:
        futures = {pool_exec.submit(_dock_one, d): d for d in decoys}
        for fut in as_completed(futures):
            decoy_rows.append(fut.result())
            done += 1
            if progress_cb:
                progress_cb(done, total)

    valid_scores = [d["score"] for d in decoy_rows if d["score"] is not None]
    pct = percentile_rank(compound_score, valid_scores) if valid_scores else None
    return {
        "compound_score": compound_score,
        "n_decoys_generated": len(decoys), "n_decoys_docked": len(valid_scores),
        "n_decoys_failed": len(decoy_rows) - len(valid_scores),
        "percentile": pct, "discrimination": discrimination_label(pct),
        "decoys": decoy_rows,
    }
