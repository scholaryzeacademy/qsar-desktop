"""
Docking enrichment test.  [metrics TESTED; docking runs on your machine]

Docks a set of KNOWN actives + decoys against a validated target and checks
whether the actives rank above the decoys. Redocking proves geometry; THIS
proves the ranking is meaningful across compounds.

Input CSV (enrichment_set.csv): columns  name,smiles,label   (label = active|decoy)
  -> use PubChem 'Canonical SMILES' for each; a wrong SMILES corrupts the result.

Run:  python enrichment_test.py cox2 enrichment_set.csv
"""
import os, sys, csv, json
import numpy as np

REFERENCE_FILENAME = "enrichment_reference.json"


def reference_path(target_id):
    from docking.profile import DOCKING_TARGETS_DIR
    return os.path.join(DOCKING_TARGETS_DIR, target_id, REFERENCE_FILENAME)


def save_reference(target_id, m, pdb_source, decoy_method, source_note, engine_name="vina", exhaustiveness=8):
    """Persists the FULL per-compound active/decoy score list (not just the
       aggregate AUC/EF already written to docking_registry.json) so a
       later-submitted compound can be ranked against this exact, already-
       vetted distribution instead of nothing. Keyed to pdb_source so a
       future re-validation against a different structure can't silently
       leave a stale (mismatched-receptor) reference in place — callers
       must check pdb_source still matches the live registry entry before
       trusting this file (see docking/enrichment.py's load_reference)."""
    path = reference_path(target_id)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    payload = {
        "target_id": target_id, "pdb_source": pdb_source,
        "decoy_method": decoy_method, "source_note": source_note,
        "engine": engine_name, "exhaustiveness": exhaustiveness,
        "metrics": {k: v for k, v in m.items() if k != "ranking"},
        "compounds": [{"name": r["name"], "smiles": r["smiles"], "label": r["label"], "score": r["score"]}
                     for r in m.get("ranking", [])],
    }
    with open(path, "w") as f:
        json.dump(payload, f, indent=2)
    return path


def dock_scores(target_id, rows, vina_only=True):
    from docking import profile as P, pipeline
    from docking.engines import VinaEngine
    prof = P.load_profile(target_id)
    engine = VinaEngine() if vina_only else None
    out = []
    for i, r in enumerate(rows, 1):
        print(f"  [{i}/{len(rows)}] {r['name']} ...", flush=True)
        try:
            res = pipeline.dock_compound(prof, r["smiles"], engine=engine)
            pose = res.get("consensus_pose")
            score = pose["score"] if pose else None
        except Exception as e:
            score = None; print("     error:", e)
        out.append({**r, "score": score})
    return out


def metrics(scored, top_frac=0.2):
    """Lower score = better binding. Returns AUC, enrichment factor, ranking."""
    from sklearn.metrics import roc_auc_score
    ok = [s for s in scored if s["score"] is not None]
    ok.sort(key=lambda s: s["score"])                     # best (most negative) first
    for rank, s in enumerate(ok, 1):
        s["rank"] = rank
    y = [1 if s["label"] == "active" else 0 for s in ok]
    scores = [-s["score"] for s in ok]                    # higher = more active-like
    n_act = sum(y)
    result = {"n_docked": len(ok), "n_failed": len(scored) - len(ok),
              "n_active": n_act, "n_decoy": len(ok) - n_act}
    if n_act and (len(ok) - n_act):
        result["auc"] = round(roc_auc_score(y, scores), 3)
        k = max(1, int(round(top_frac * len(ok))))
        found = sum(1 for s in ok[:k] if s["label"] == "active")
        result["ef_top"] = round((found / k) / (n_act / len(ok)), 2)
        result["top_frac"] = top_frac
        result["active_ranks"] = [s["rank"] for s in ok if s["label"] == "active"]
    result["ranking"] = [{"rank": s["rank"], "name": s["name"], "label": s["label"],
                          "score": s["score"], "smiles": s.get("smiles")} for s in ok]
    return result


def verdict(m):
    a = m.get("auc")
    if a is None:
        return "need both actives and decoys that docked"
    if a >= 0.8:
        return "STRONG separation — docking ranks actives well for this target"
    if a >= 0.65:
        return "MODERATE separation — some ranking signal; use with QSAR"
    return "WEAK separation — docking scores don't rank well here; lean on QSAR ranking"


def main():
    if len(sys.argv) < 3:
        print("usage: python enrichment_test.py <target_id> <set.csv>"); return
    target_id, path = sys.argv[1], sys.argv[2]
    rows = [r for r in csv.DictReader(open(path)) if r.get("smiles", "").strip()]
    print(f"Docking {len(rows)} compounds against '{target_id}' (Vina)…")
    scored = dock_scores(target_id, rows)
    m = metrics(scored)
    print("\n=== Enrichment ===")
    print(f"docked {m['n_docked']} ({m['n_active']} active / {m['n_decoy']} decoy), "
          f"failed {m['n_failed']}")
    if "auc" in m:
        print(f"AUC: {m['auc']}   EF@{int(m['top_frac']*100)}%: {m['ef_top']}   "
              f"active ranks: {m['active_ranks']}")
    print("verdict:", verdict(m))
    print("\nrank  score   label   name")
    for r in m["ranking"]:
        print(f"{r['rank']:>3}  {r['score']:>6}  {r['label']:<7} {r['name']}")
    json.dump(m, open("enrichment_result.json", "w"), indent=2)
    print("\nsaved -> enrichment_result.json")


if __name__ == "__main__":
    main()
