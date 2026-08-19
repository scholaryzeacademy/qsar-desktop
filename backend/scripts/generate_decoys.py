"""
DUD-E-style decoy generation for docking enrichment tests.

Replaces the previous proxy ("this target's own weakest measured binders as
'decoys'" — see the honesty note in validate_target.py's module docstring)
with real, independently-selected decoys, following the same two-part
DUD-E recipe (Mysinger et al. 2012), adapted to run entirely offline:

  1. PROPERTY-MATCHED: a decoy must resemble a real active's bulk
     physicochemical properties (MW, LogP, HBD, HBA, rotatable bonds, net
     charge) within tolerance — so it's a physically plausible drug-like
     molecule of similar size/polarity, not a random reject.
  2. TOPOLOGICALLY DISSIMILAR: a decoy must NOT be a close 2D analog of any
     active (Morgan/ECFP4 Tanimoto < 0.25 to every active) — otherwise it
     would trivially dock well by being chemically almost the same molecule,
     defeating the point of the test.

CANDIDATE POOL: real ChEMBL compounds curated for OTHER targets
(models/curated/*.csv, ~64 targets, ~100k+ compounds total), excluding the
target under test and excluding any SMILES that also appears in the target's
own dataset (a compound tested against multiple targets could coincidentally
also bind the one under test). This project has no internet-based decoy
database (e.g. ZINC) wired up, so "presumed inactive" here means "curated
for a different target's assay, not this one" — a real, disclosed
methodological choice, not a hidden approximation. Recorded per-run in the
returned 'source' string so it's never confused with a true confirmed-
inactive DUD-E/ZINC decoy set.

Usage (library):
    from scripts.generate_decoys import build_enrichment_set
    rows = build_enrichment_set("CHEMBL203_EGFR", n_actives=8, n_decoys_per_active=5)

Usage (CLI, for inspection):
    python scripts/generate_decoys.py CHEMBL203_EGFR
"""
import argparse
import glob
import os
import random

import numpy as np
import pandas as pd
from rdkit import Chem, RDLogger
from rdkit.Chem import Crippen, Descriptors, rdFingerprintGenerator, rdMolDescriptors
from rdkit import DataStructs

RDLogger.DisableLog("rdApp.*")

CURATED_DIR = "models/curated"   # cwd-relative — repo root, same as models/ everywhere else
POOL_CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_decoy_pool_cache.pkl")
                                  # own dir, NOT cwd-relative — a cache file, and this module is
                                  # reachable live from app.py's /api/docking/enrichment/fresh
                                  # with the server's cwd (repo root), not scripts/'s own dir

_morgan = rdFingerprintGenerator.GetMorganGenerator(radius=2, fpSize=2048)

# DUD-E-style property tolerances (Mysinger et al. 2012, Table 1 — MW/logP/RotB
# tightened slightly since our pool per-target is much smaller than ZINC's).
TOL_MW = 30.0
TOL_LOGP = 1.0
TOL_HBD = 1
TOL_HBA = 2
TOL_ROTB = 2
MAX_TANIMOTO = 0.25


def _props(mol):
    return {
        "mw": Descriptors.MolWt(mol),
        "logp": Crippen.MolLogP(mol),
        "hbd": rdMolDescriptors.CalcNumHBD(mol),
        "hba": rdMolDescriptors.CalcNumHBA(mol),
        "rotb": rdMolDescriptors.CalcNumRotatableBonds(mol),
        "charge": Chem.GetFormalCharge(mol),
    }


def _fp(mol):
    return _morgan.GetFingerprint(mol)


def _target_chembl_prefix(target_id):
    """models/curated/<CHEMBL_ID>.csv is named by the target's ChEMBL ID,
       which is the leading token of target_id (e.g. 'CHEMBL203' from
       'CHEMBL203_EGFR')."""
    return target_id.split("_", 1)[0]


def build_pool(exclude_target_id=None, force_rebuild=False):
    """Loads + featurises every OTHER target's curated compounds into one
       pool DataFrame (smiles, source_target, mw, logp, hbd, hba, rotb,
       charge, fp). Cached to disk (properties/fingerprints are the slow
       part) since this pool is reused across every target's decoy run."""
    if os.path.exists(POOL_CACHE) and not force_rebuild:
        pool = pd.read_pickle(POOL_CACHE)
    else:
        rows = []
        for path in sorted(glob.glob(os.path.join(CURATED_DIR, "*.csv"))):
            src = os.path.splitext(os.path.basename(path))[0]  # e.g. CHEMBL203
            df = pd.read_csv(path)
            for smi in df["smiles"].dropna().unique():
                mol = Chem.MolFromSmiles(smi)
                if mol is None or mol.GetNumHeavyAtoms() == 0:
                    continue
                p = _props(mol)
                fp = _fp(mol)
                rows.append({"smiles": smi, "source_target": src,
                            "mw": p["mw"], "logp": p["logp"], "hbd": p["hbd"],
                            "hba": p["hba"], "rotb": p["rotb"], "charge": p["charge"],
                            "fp_bits": fp.ToBitString()})
        pool = pd.DataFrame(rows)
        os.makedirs(os.path.dirname(POOL_CACHE), exist_ok=True)
        pool.to_pickle(POOL_CACHE)

    if exclude_target_id:
        prefix = _target_chembl_prefix(exclude_target_id)
        pool = pool[pool["source_target"] != prefix].reset_index(drop=True)
    return pool


def _fp_from_bits(bitstring):
    return DataStructs.CreateFromBitString(bitstring)


def select_decoys(actives_df, pool, n_per_active=5, seed=42, max_pool_check=None):
    """actives_df: DataFrame with 'smiles' (the real potent compounds).
       Returns a list of {name, smiles, label:'decoy', source_target,
       matched_active} — property-matched to at least one active, and
       Tanimoto-dissimilar (< MAX_TANIMOTO) to EVERY active."""
    rng = random.Random(seed)
    own_smiles = set(actives_df["smiles"])
    candidate_pool = pool[~pool["smiles"].isin(own_smiles)]
    if max_pool_check:
        candidate_pool = candidate_pool.sample(n=min(max_pool_check, len(candidate_pool)),
                                                random_state=seed)

    active_mols = [Chem.MolFromSmiles(s) for s in actives_df["smiles"]]
    active_props = [_props(m) for m in active_mols if m is not None]
    active_fps = [_fp(m) for m in active_mols if m is not None]

    cand_fps = [_fp_from_bits(b) for b in candidate_pool["fp_bits"]]

    chosen = {}   # smiles -> row (dedup across actives)
    per_active_pool = {i: [] for i in range(len(active_props))}

    for idx, (_, cand) in enumerate(candidate_pool.iterrows()):
        cfp = cand_fps[idx]
        for ai, ap in enumerate(active_props):
            if (abs(cand["mw"] - ap["mw"]) > TOL_MW or
                abs(cand["logp"] - ap["logp"]) > TOL_LOGP or
                abs(cand["hbd"] - ap["hbd"]) > TOL_HBD or
                abs(cand["hba"] - ap["hba"]) > TOL_HBA or
                abs(cand["rotb"] - ap["rotb"]) > TOL_ROTB or
                cand["charge"] != ap["charge"]):
                continue
            # must be dissimilar to EVERY active, not just the one it matched on
            max_sim = max(DataStructs.TanimotoSimilarity(cfp, afp) for afp in active_fps)
            if max_sim >= MAX_TANIMOTO:
                continue
            per_active_pool[ai].append(idx)

    for ai in range(len(active_props)):
        candidates = per_active_pool[ai][:]
        rng.shuffle(candidates)
        picked = 0
        for idx in candidates:
            if picked >= n_per_active:
                break
            row = candidate_pool.iloc[idx]
            if row["smiles"] in chosen:
                continue
            chosen[row["smiles"]] = {
                "name": f"decoy_{row['source_target']}_{len(chosen)}",
                "smiles": row["smiles"], "label": "decoy",
                "source_target": row["source_target"], "matched_active_idx": ai,
            }
            picked += 1

    return list(chosen.values())


def build_enrichment_set(target_id, n_actives=8, n_decoys_per_active=5, seed=42):
    """Full replacement for validate_target.py's build_enrichment_rows():
       real actives (top-N by measured pChEMBL, same as before) + real
       property-matched/topologically-dissimilar decoys (new)."""
    csv_path = os.path.join("models", target_id, "Data", "full_cleaned.csv")
    df = pd.read_csv(csv_path).dropna(subset=["smiles", "pchembl_value"])
    df = df.sort_values("pchembl_value", ascending=False)
    actives_df = df.head(n_actives)

    pool = build_pool(exclude_target_id=target_id)
    decoys = select_decoys(actives_df, pool, n_per_active=n_decoys_per_active, seed=seed)

    rows = [{"name": f"active_{i}", "smiles": s, "label": "active"}
            for i, s in enumerate(actives_df["smiles"])]
    rows += [{"name": d["name"], "smiles": d["smiles"], "label": "decoy"} for d in decoys]
    return rows, decoys   # decoys returned separately too, for provenance logging


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("target_id")
    ap.add_argument("--n-actives", type=int, default=8)
    ap.add_argument("--n-decoys-per-active", type=int, default=5)
    args = ap.parse_args()

    rows, decoys = build_enrichment_set(args.target_id, args.n_actives, args.n_decoys_per_active)
    n_active = sum(1 for r in rows if r["label"] == "active")
    n_decoy = sum(1 for r in rows if r["label"] == "decoy")
    print(f"{n_active} actives, {n_decoy} decoys (target {args.n_actives * args.n_decoys_per_active} max, "
          f"fewer if property-matching/dissimilarity pruned the pool hard)")
    for d in decoys[:10]:
        print(f"  decoy from {d['source_target']}: {d['smiles']}")


if __name__ == "__main__":
    main()
