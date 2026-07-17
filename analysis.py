"""
============================================================
  MULTI-TARGET / DISEASE ANALYSIS  (analysis.py)
============================================================
  Predict a set of SMILES against SEVERAL targets at once (or a whole
  disease's target group), then analyse the result from several angles
  a chemist actually uses:

    - POTENCY MATRIX   : compound x target predicted potency (+ confidence)
    - SELECTIVITY      : is a compound selective for one target, or broad?
    - POLYPHARMACOLOGY : multi-target candidates (desirable for complex
                         diseases, e.g. Alzheimer's AChE+BChE)
    - CONSENSUS RANK   : overall best candidates across the disease's
                         targets, ranked by confidence-weighted evidence
    - COVERAGE         : how much of each compound's profile is trustworthy
                         (in how many targets it is in-domain)
    - ADMET            : drug-likeness / liability profile per compound

  All ranking uses the conformal LOWER bound (confidently-potent), mirroring
  the single-target tool. Out-of-domain cells are shown but never counted as
  evidence.
============================================================"""

import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd

import serve
import pipeline as P
import admet as ADMET

# thresholds (configurable)
ACTIVE_CUT = 6.0     # pIC50 >= 6  (IC50 <= 1 uM) counts as "active" (on the lower bound)
SELECTIVE_GAP = 1.0  # >= 1 log-unit gap to the next target => "selective"


def predict_matrix(smiles_list, target_ids, model=None):
    """Return per-target prediction frames keyed consistently by input SMILES.
       Skips unknown/failed targets (reported in 'skipped_targets')."""
    smiles_list = [s.strip() for s in smiles_list if s and s.strip()]
    per_target, meta, skipped = {}, {}, []
    for tid in target_ids:
        try:
            asset, rec = serve.load_model(tid)
        except Exception as e:
            skipped.append({"target_id": tid, "reason": str(e)}); continue
        df = P.predict_stream(smiles_list, asset, model_name=model, batch=2000)
        conf = P._conformal_for(asset, model or asset["best_name"])
        lvl = int(round(conf["confidence"] * 100)) if conf else 90
        df = df.reset_index(drop=True)
        per_target[tid] = {"df": df, "lower_col": f"Lower_{lvl}"}
        m = rec.get("metrics_by_model", {}).get(model or asset["best_name"], {})
        meta[tid] = {"name": rec["name"], "status": rec["status"],
                     "model": model or asset["best_name"],
                     "spearman": m.get("spearman"), "coverage": m.get("conformal_coverage")}
    return smiles_list, per_target, meta, skipped


def analyse(smiles_list, target_ids, model=None, active_cut=ACTIVE_CUT, sel_gap=SELECTIVE_GAP):
    smiles, per_target, meta, skipped = predict_matrix(smiles_list, target_ids, model)
    tids = list(per_target.keys())

    # ---- assemble the matrix: per input SMILES, a cell per target ----
    rows = []
    for i, smi in enumerate(smiles):
        std = None
        cells = {}
        for tid in tids:
            d = per_target[tid]["df"].iloc[i]
            lc = per_target[tid]["lower_col"]
            std = std or d.get("Standardised_SMILES")
            cells[tid] = {
                "pred": _num(d.get("Predicted_pIC50")),
                "lower": _num(d.get(lc)),
                "in_domain": bool(d.get("In_AD")),
                "pi_low": _num(d.get("PI_low")), "pi_high": _num(d.get("PI_high")),
                "parsed": bool(d.get("Parsed_OK")),
            }
        rows.append({"input_smiles": smi, "smiles": std, "cells": cells})

    # ---- per-compound analyses ----
    for r in rows:
        indom = {t: c for t, c in r["cells"].items() if c["in_domain"] and c["lower"] is not None}
        r["coverage"] = {"in_domain_targets": len(indom), "total_targets": len(tids),
                         "fraction": round(len(indom) / len(tids), 2) if tids else 0}
        # selectivity: gap between best and 2nd-best in-domain target (by lower bound)
        if len(indom) >= 2:
            ranked = sorted(indom.items(), key=lambda kv: kv[1]["lower"], reverse=True)
            best_t, best_v = ranked[0][0], ranked[0][1]["lower"]
            gap = best_v - ranked[1][1]["lower"]
            r["selectivity"] = {"best_target": best_t, "best_lower": round(best_v, 3),
                                "gap_to_next": round(gap, 3),
                                "call": "selective" if gap >= sel_gap else "multi-target"}
        elif len(indom) == 1:
            t, c = next(iter(indom.items()))
            r["selectivity"] = {"best_target": t, "best_lower": round(c["lower"], 3),
                                "gap_to_next": None, "call": "single in-domain target"}
        else:
            r["selectivity"] = {"best_target": None, "call": "no in-domain target"}
        # polypharmacology: how many targets confidently active (lower bound >= cut)
        active = [t for t, c in indom.items() if c["lower"] >= active_cut]
        r["active_targets"] = active
        r["n_active"] = len(active)
        r["multi_target"] = len(active) >= 2
        # overall score for the disease: mean lower bound over in-domain targets
        r["mean_lower_in_domain"] = round(float(np.mean([c["lower"] for c in indom.values()])), 3) if indom else None

    # ---- consensus ranking across the disease (confidence-weighted) ----
    scored = [r for r in rows if r["mean_lower_in_domain"] is not None]
    scored.sort(key=lambda r: (r["n_active"], r["mean_lower_in_domain"]), reverse=True)
    for rank, r in enumerate(scored, 1):
        r["consensus_rank"] = rank

    # ---- best compound per target ----
    best_per_target = {}
    for tid in tids:
        cand = [(r["smiles"], r["cells"][tid]["lower"]) for r in rows
                if r["cells"][tid]["in_domain"] and r["cells"][tid]["lower"] is not None]
        cand.sort(key=lambda x: x[1], reverse=True)
        best_per_target[tid] = [{"smiles": s, "lower": round(v, 3)} for s, v in cand[:5]]

    # ---- multi-target candidates (polypharmacology view) ----
    multi = [{"smiles": r["smiles"], "active_targets": r["active_targets"],
              "n_active": r["n_active"], "mean_lower": r["mean_lower_in_domain"]}
             for r in rows if r["multi_target"]]
    multi.sort(key=lambda x: (x["n_active"], x["mean_lower"]), reverse=True)

    # ---- selective candidates ----
    selective = [{"smiles": r["smiles"], "target": r["selectivity"]["best_target"],
                  "lower": r["selectivity"]["best_lower"], "gap": r["selectivity"]["gap_to_next"]}
                 for r in rows if r["selectivity"].get("call") == "selective"]
    selective.sort(key=lambda x: x["gap"], reverse=True)

    # ---- ADMET per compound (deterministic layer) ----
    admet = {r["smiles"]: ADMET.admet_profile(r["input_smiles"]) for r in rows if r["smiles"]}

    return {
        "targets": [{"target_id": t, **meta[t]} for t in tids],
        "skipped_targets": skipped,
        "n_compounds": len(smiles),
        "active_cut": active_cut, "selective_gap": sel_gap,
        "matrix": rows,
        "consensus_ranking": [{"consensus_rank": r["consensus_rank"], "smiles": r["smiles"],
                               "n_active": r["n_active"], "mean_lower": r["mean_lower_in_domain"],
                               "coverage": r["coverage"]["fraction"]} for r in scored],
        "multi_target_candidates": multi,
        "selective_candidates": selective,
        "best_per_target": best_per_target,
        "admet": admet,
        "disclaimer": ("Prioritisation aid. Only in-domain cells are evidence; out-of-domain "
                       "predictions are shown greyed and never counted. Ranking uses the "
                       f"{int(SELECTIVE_GAP)}-log selectivity gap and pIC50>={active_cut} (on the "
                       "confidence lower bound) as the 'active' threshold."),
    }


def _num(v):
    try:
        if v is None or pd.isna(v):
            return None
        return round(float(v), 3)
    except Exception:
        return None


if __name__ == "__main__":
    import json
    smis = ["CC(C)Cc1ccc(C(C)C(=O)O)cc1", "Cc1ccc(-c2ccncc2)cc1",
            "CCc1ccc(C(F)(F)F)cc1", "CC(=O)Oc1ccccc1C(=O)O"]
    out = analyse(smis, ["cox2", "ache"])
    print("targets:", [t["target_id"] for t in out["targets"]], "| skipped:", out["skipped_targets"])
    print("\nConsensus ranking:")
    for r in out["consensus_ranking"]:
        print(f"  #{r['consensus_rank']} {r['smiles'][:26]:28} active_in={r['n_active']} mean_lower={r['mean_lower']} cov={r['coverage']}")
    print("\nMulti-target candidates:", [(m['smiles'][:20], m['n_active']) for m in out["multi_target_candidates"]])
    print("Selective candidates:", [(s['smiles'][:20], s['target'], s['gap']) for s in out["selective_candidates"]])
    print("\nBest per target:")
    for t, lst in out["best_per_target"].items():
        print(" ", t, [(x['smiles'][:18], x['lower']) for x in lst[:2]])
