"""
============================================================
  SCREEN PIPELINE  (serving/screen.py)
============================================================
  CLAUDE.md §7.1 — the headline feature: an explicit, ordered 8-step
  pipeline the researcher can watch run, ending in a ranked, honestly-
  caveated shortlist with every signal attached.

    STEP 1  Parse & standardise SMILES
    STEP 2  Featurise (folded into step 4's target.predict_smiles call —
            see the note there; still reported as its own visible step)
    STEP 3  Applicability-domain check
    STEP 4  QSAR potency prediction (pIC50) + confidence tier
    STEP 5  ADMET profiling (deterministic + learned, worker-optional)
    STEP 6  Docking — ONLY if the target is docking-validated
    STEP 7  Rank / fuse the evidence into a final shortlist
    STEP 8  Finalise + attach a methods/caveats note

  This module is pure orchestration + a progress callback; it owns no
  job/thread state (app.py wraps it in a background thread + job dict,
  matching the existing ADMET/docking job pattern).
============================================================
"""
from . import model_adapter as MA
from . import featurize as F
import admet as ADMET

try:
    from docking import availability as DOCK_AVAIL
    from docking import pipeline as DOCK_PIPE
    from docking import profile as DOCK_PROFILE
except Exception:
    DOCK_AVAIL = DOCK_PIPE = DOCK_PROFILE = None

STEPS = {
    1: "Parsing & standardising SMILES",
    2: "Featurising (RDKit 2D + MACCS + Morgan)",
    3: "Checking applicability domain",
    4: "Predicting potency (Chemprop + AutoGluon)",
    5: "Profiling ADMET",
    6: "Docking",
    7: "Ranking & fusing evidence",
    8: "Finalising results",
}

DOCK_WEIGHT = 0.35   # fraction of the fused rank score docking contributes, ONLY
                     # when the target is docking-validated and docking actually ran


def _noop(step, label, done=None, total=None):
    pass


def _rank_score(values, higher_is_better):
    """Map a list of numeric values (None allowed) to a 0..1 rank-based score
       within THIS batch — deliberately not the raw units, so pIC50 and Vina
       kcal/mol never get silently averaged on incompatible scales."""
    idx = [i for i, v in enumerate(values) if v is not None]
    if not idx:
        return [None] * len(values)
    ordered = sorted(idx, key=lambda i: values[i], reverse=higher_is_better)
    score = [None] * len(values)
    n = len(ordered)
    for rank, i in enumerate(ordered):
        score[i] = 1.0 - (rank / max(n - 1, 1))   # best=1.0, worst=0.0
    return score


def run(target_id, smiles_list, make_diagram=True, progress=None):
    """Runs the full pipeline synchronously; progress(step, label, done, total)
       is called at each transition (and during step 6, per compound, since
       docking is the slow part). Returns the result dict."""
    progress = progress or _noop
    smiles_list = [s.strip() for s in smiles_list if s and s.strip()]

    progress(1, STEPS[1])
    std = [F.standardise_smiles(s) for s in smiles_list]
    parsed_ok = [s is not None for s in std]
    skipped = [smiles_list[i] for i, ok in enumerate(parsed_ok) if not ok]
    # keep RAW input and STANDARDISED SMILES paired throughout — every dict
    # below is keyed by the standardised form (what predict_smiles/admet
    # return), never a mix of the two, or lookups would silently miss.
    valid_pairs = [(smiles_list[i], std[i]) for i, ok in enumerate(parsed_ok) if ok]
    valid_inputs = [p[0] for p in valid_pairs]
    valid_std = [p[1] for p in valid_pairs]

    progress(2, STEPS[2])   # folded into target.predict_smiles below (steps 2-4
                            # share one featurisation pass for correctness + speed)
    progress(3, STEPS[3])

    target = MA.load_target(target_id)   # BucketError propagates to the caller

    progress(4, STEPS[4])
    qsar = {} if not valid_inputs else {
        row["Standardised_SMILES"]: row
        for row in target.predict_smiles(valid_inputs).to_dict("records")
    }

    progress(5, STEPS[5])
    admet_list = ADMET.admet_profiles(valid_inputs) if valid_inputs else []
    admet_by_smiles = {p["standardised_smiles"]: p for p in admet_list if p.get("parsed_ok")}

    dock_by_smiles = {}
    docking_note = None
    dock_validated = False
    if DOCK_PROFILE is not None:
        try:
            dprofile = DOCK_PROFILE.load_profile(target_id)
            dock_validated = bool(dprofile.get("validated"))
        except Exception:
            dprofile = None
        dock_ready = bool(DOCK_AVAIL and DOCK_AVAIL.status()["ready"])
        if dprofile is not None and dock_validated and dock_ready:
            progress(6, STEPS[6], 0, len(valid_std))
            for i, s in enumerate(valid_std):
                dock_by_smiles[s] = DOCK_PIPE.dock_compound(dprofile, s, make_diagram=make_diagram)
                progress(6, STEPS[6], i + 1, len(valid_std))
        else:
            docking_note = ("Docking skipped: this target is not docking-validated." if dprofile is not None
                            and not dock_validated else
                            "Docking skipped: docking engine not available on this machine." if not dock_ready
                            else "Docking skipped: no docking profile for this target.")
            progress(6, STEPS[6] + " — skipped")
    else:
        docking_note = "Docking skipped: the docking package is not importable."
        progress(6, STEPS[6] + " — skipped")

    progress(7, STEPS[7])
    qsar_vals = [qsar.get(s, {}).get("Predicted_pIC50") if qsar.get(s, {}).get("In_AD") else None
                 for s in valid_std]
    dock_vals = [dock_by_smiles.get(s, {}).get("vina_score") for s in valid_std]
    q_score = _rank_score(qsar_vals, higher_is_better=True)
    d_score = _rank_score(dock_vals, higher_is_better=False)   # more negative Vina = better

    shortlist = []
    for i, smi in enumerate(valid_std):
        q = qsar.get(smi, {})
        d = dock_by_smiles.get(smi)
        a = admet_by_smiles.get(smi)
        has_dock_score = dock_validated and d_score[i] is not None
        if has_dock_score and q_score[i] is not None:
            fused = (1 - DOCK_WEIGHT) * q_score[i] + DOCK_WEIGHT * d_score[i]
        else:
            fused = q_score[i]   # QSAR-only when docking didn't run/wasn't validated

        caveats = []
        if not q.get("In_AD", False):
            caveats.append("Outside the QSAR model's training chemistry — potency not trusted.")
        if d and d.get("status") not in ("ok", None):
            caveats.append(f"Docking: {d.get('reason') or d.get('status')}.")
        if a and a.get("n_alerts"):
            caveats.append(f"{a['n_alerts']} structural alert(s) (PAINS/Brenk/NIH) — informational, not a filter.")

        shortlist.append({
            "input_smiles": valid_inputs[i],
            "smiles": smi,
            "qsar": {
                "predicted_pIC50": q.get("Predicted_pIC50") if q.get("In_AD") else None,
                "in_domain": bool(q.get("In_AD", False)),
                "ad_z": q.get("AD_z"),
                "confidence": q.get("Confidence"),
                "confidence_label": q.get("Confidence_Label"),
            },
            "docking": ({
                "vina_score": d.get("vina_score"),
                "confidence": d.get("confidence"),
                "status": d.get("status"),
                "interaction_png": d.get("interaction_png"),
                "residue_overlap_pct": d.get("residue_overlap_pct"),
            } if d else None),
            "admet": a,
            "fused_score": round(fused, 4) if fused is not None else None,
            "caveats": caveats,
        })

    shortlist.sort(key=lambda r: (r["fused_score"] is None, -(r["fused_score"] or 0)))
    for rank, r in enumerate(shortlist, 1):
        r["rank"] = rank

    progress(8, STEPS[8])
    methods_note = (
        f"Screened {len(smiles_list)} input SMILES against target '{target_id}'. "
        f"{len(skipped)} could not be parsed by RDKit and were excluded. QSAR potency "
        f"(pIC50) is from the target's shipped Chemprop+AutoGluon model; only in-domain "
        f"compounds (mean |z| <= 3.0 vs. the training set) receive a trusted potency value. "
        + (f"Docking used AutoDock Vina against a redocking+enrichment-validated receptor "
           f"and contributed {int(DOCK_WEIGHT*100)}% of the fused rank score."
           if dock_validated and dock_by_smiles else
           f"Docking was not used in ranking ({docking_note or 'not available for this target'}).")
        + " ADMET flags (Lipinski/Veber/PAINS/Brenk/NIH) are informational caveats, not filters — "
          "nothing was excluded for violating them. This is a prioritisation aid, not a substitute for assays."
    )

    return {
        "target_id": target_id,
        "counts": {"submitted": len(smiles_list), "parsed": len(valid_inputs), "skipped": len(skipped)},
        "skipped": skipped,
        "shortlist": shortlist,
        "docking_used": bool(dock_validated and dock_by_smiles),
        "docking_note": docking_note,
        "methods_note": methods_note,
    }
