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
                         targets, ranked by in-domain evidence
    - COVERAGE         : how much of each compound's profile is trustworthy
                         (in how many targets it is in-domain)
    - ADMET            : drug-likeness / liability profile per compound

  Ranking uses the point prediction (Predicted_pIC50) — the shipped
  AutoGluon models don't carry a per-compound conformal interval (see
  serving/confidence.py), so this is honestly a point estimate, not a
  confidence lower bound. Out-of-domain cells are shown but never
  counted as evidence.
============================================================"""

import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd

from serving import model_adapter as MA
import admet as ADMET

# thresholds (configurable)
ACTIVE_CUT = 6.0     # pIC50 >= 6  (IC50 <= 1 uM) counts as "active" (point prediction, in-domain only)
SELECTIVE_GAP = 1.0  # >= 1 log-unit gap to the next target => "selective"


def predict_matrix(smiles_list, target_ids):
    """Return per-target prediction frames keyed consistently by input SMILES.
       Skips unknown/failed targets (reported in 'skipped_targets')."""
    smiles_list = [s.strip() for s in smiles_list if s and s.strip()]
    per_target, meta, skipped = {}, {}, []
    for tid in target_ids:
        try:
            target = MA.load_target(tid)
        except Exception as e:
            skipped.append({"target_id": tid, "reason": str(e)}); continue
        df = target.predict_smiles(smiles_list).reset_index(drop=True)
        per_target[tid] = df
        m = target.metrics
        meta[tid] = {"name": target.name, "test_r2": m.get("R2_Test"), "test_rmse": m.get("RMSE_Test")}
    return smiles_list, per_target, meta, skipped


def analyse(smiles_list, target_ids, active_cut=ACTIVE_CUT, sel_gap=SELECTIVE_GAP):
    smiles, per_target, meta, skipped = predict_matrix(smiles_list, target_ids)
    tids = list(per_target.keys())

    # ---- assemble the matrix: per input SMILES, a cell per target ----
    rows = []
    for i, smi in enumerate(smiles):
        std = None
        cells = {}
        for tid in tids:
            d = per_target[tid].iloc[i]
            std = std or d.get("Standardised_SMILES")
            cells[tid] = {
                "pred": _num(d.get("Predicted_pIC50")) if bool(d.get("In_AD")) else None,
                "in_domain": bool(d.get("In_AD")),
                "confidence": d.get("Confidence"),
                "parsed": bool(d.get("Parsed_OK")),
            }
        rows.append({"input_smiles": smi, "smiles": std, "cells": cells})

    # ---- per-compound analyses ----
    for r in rows:
        indom = {t: c for t, c in r["cells"].items() if c["in_domain"] and c["pred"] is not None}
        r["coverage"] = {"in_domain_targets": len(indom), "total_targets": len(tids),
                         "fraction": round(len(indom) / len(tids), 2) if tids else 0}
        # selectivity: gap between best and 2nd-best in-domain target
        if len(indom) >= 2:
            ranked = sorted(indom.items(), key=lambda kv: kv[1]["pred"], reverse=True)
            best_t, best_v = ranked[0][0], ranked[0][1]["pred"]
            gap = best_v - ranked[1][1]["pred"]
            r["selectivity"] = {"best_target": best_t, "best_pred": round(best_v, 3),
                                "gap_to_next": round(gap, 3),
                                "call": "selective" if gap >= sel_gap else "multi-target"}
        elif len(indom) == 1:
            t, c = next(iter(indom.items()))
            r["selectivity"] = {"best_target": t, "best_pred": round(c["pred"], 3),
                                "gap_to_next": None, "call": "single in-domain target"}
        else:
            r["selectivity"] = {"best_target": None, "call": "no in-domain target"}
        # polypharmacology: how many targets confidently active
        active = [t for t, c in indom.items() if c["pred"] >= active_cut]
        r["active_targets"] = active
        r["n_active"] = len(active)
        r["multi_target"] = len(active) >= 2
        # overall score for the disease: mean predicted pIC50 over in-domain targets
        r["mean_pred_in_domain"] = round(float(np.mean([c["pred"] for c in indom.values()])), 3) if indom else None

    # ---- consensus ranking across the disease ----
    scored = [r for r in rows if r["mean_pred_in_domain"] is not None]
    scored.sort(key=lambda r: (r["n_active"], r["mean_pred_in_domain"]), reverse=True)
    for rank, r in enumerate(scored, 1):
        r["consensus_rank"] = rank

    # ---- best compound per target ----
    best_per_target = {}
    for tid in tids:
        cand = [(r["smiles"], r["cells"][tid]["pred"]) for r in rows
                if r["cells"][tid]["in_domain"] and r["cells"][tid]["pred"] is not None]
        cand.sort(key=lambda x: x[1], reverse=True)
        best_per_target[tid] = [{"smiles": s, "pred": round(v, 3)} for s, v in cand[:5]]

    # ---- multi-target candidates (polypharmacology view) ----
    multi = [{"smiles": r["smiles"], "active_targets": r["active_targets"],
              "n_active": r["n_active"], "mean_pred": r["mean_pred_in_domain"]}
             for r in rows if r["multi_target"]]
    multi.sort(key=lambda x: (x["n_active"], x["mean_pred"]), reverse=True)

    # ---- selective candidates ----
    selective = [{"smiles": r["smiles"], "target": r["selectivity"]["best_target"],
                  "pred": r["selectivity"]["best_pred"], "gap": r["selectivity"]["gap_to_next"]}
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
                               "n_active": r["n_active"], "mean_pred": r["mean_pred_in_domain"],
                               "coverage": r["coverage"]["fraction"]} for r in scored],
        "multi_target_candidates": multi,
        "selective_candidates": selective,
        "best_per_target": best_per_target,
        "admet": admet,
        "disclaimer": ("Prioritisation aid. Only in-domain cells are evidence; out-of-domain "
                       "predictions are shown greyed and never counted. Ranking uses the "
                       f"{int(SELECTIVE_GAP)}-log selectivity gap and pIC50>={active_cut} on the "
                       "predicted point estimate (in-domain only) as the 'active' threshold — the "
                       "shipped models do not carry a per-compound confidence interval, see "
                       "each target's Test RMSE for its own held-out error."),
    }


def _num(v):
    try:
        if v is None or pd.isna(v):
            return None
        return round(float(v), 3)
    except Exception:
        return None
