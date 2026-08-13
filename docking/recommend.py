"""Disease -> ranked target -> 'why this structure' evidence.

Backs three read-only API endpoints (see app.py): a disease list, the
targets associated with a chosen disease (ranked by disease-association
score), and the full evidence bundle behind one target's recommended
docking structure.

Scoped to the targets we actually have QSAR models for (see
scripts.batch_validate.usable_targets, ~52 today) — panel_results_v2.csv
covers ~669 genes total, most of which have no trained potency model and
no docking receptor at all; extending this beyond our QSAR panel is future
work, not this phase.

Two evidence sources are kept separate and never conflated:
  - "our_validation": what docking_registry.json actually proved via real
    Vina redocking (scripts/validate_target.py) — the only thing that
    earns the 'validated' badge.
  - "panel_evidence": panel_results_v2.csv's crystallographic context
    (resolution/RSCC/RSR/rank) for the matching gene — supporting context,
    not proof; see scripts/panel_candidates.py for why the CSV's own
    top pick can't be trusted blindly (e.g. PDGFRB's best-ranked structure
    turned out to be a bare sugar, not an inhibitor).
"""
import functools
import os

import pandas as pd

from scripts.batch_validate import gene_for_target, usable_targets
from scripts.panel_candidates import panel_evidence, PANEL_CSV
from docking.profile import load_registry
from serving import model_adapter as MA


@functools.lru_cache(maxsize=1)
def _panel_df():
    if not os.path.exists(PANEL_CSV):
        return None
    return pd.read_csv(PANEL_CSV)


@functools.lru_cache(maxsize=1)
def _target_gene_map():
    """(target_id -> gene, gene -> target_id) for our QSAR-modeled targets."""
    t2g = {tid: gene_for_target(tid) for tid in usable_targets()}
    g2t = {g: t for t, g in t2g.items()}
    return t2g, g2t


def list_diseases():
    """Diseases from the panel CSV that have >=1 associated target among
       ours, sorted by name."""
    df = _panel_df()
    if df is None:
        return []
    _, g2t = _target_gene_map()
    ours = df[df["targetSymbol"].isin(g2t.keys())]
    out = (ours[["diseaseId", "diseaseName", "is_therapeutic_area"]]
           .drop_duplicates(subset=["diseaseId"])
           .sort_values("diseaseName"))
    return [
        {"disease_id": r.diseaseId, "name": r.diseaseName, "is_therapeutic_area": bool(r.is_therapeutic_area)}
        for r in out.itertuples()
    ]


def targets_for_disease(disease_id):
    """EVERY protein target associated with disease_id in the Version 2 CSV
       (targetSymbol column), ranked by disease-association score (desc) —
       not just the subset we happen to have a trained QSAR model for. Each
       row carries has_qsar_model so the UI can show the full disease-target
       landscape while making clear which ones can actually be predicted/
       docked against; validation/QSAR fields are only populated when a
       model exists (never invented for the rest)."""
    df = _panel_df()
    if df is None:
        return []
    _, g2t = _target_gene_map()
    rows = df[df["diseaseId"] == disease_id].sort_values("score", ascending=False)
    reg = load_registry()
    meta_by_id = {m["target_id"]: m["metrics"] for m in MA.list_targets_meta()}

    out = []
    seen = set()
    for r in rows.itertuples():
        symbol = r.targetSymbol
        if symbol in seen:   # a gene can appear more than once per disease in the CSV; keep the first (highest-scored, already sorted)
            continue
        seen.add(symbol)
        tid = g2t.get(symbol)
        has_model = tid is not None
        reg_entry = (reg.get(tid) or {}) if has_model else {}
        metrics = (meta_by_id.get(tid) or {}) if has_model else {}
        out.append({
            "target_id": tid,
            "target_symbol": symbol,
            "has_qsar_model": has_model,
            "disease_score": round(float(r.score), 4),
            "validated": bool(reg_entry.get("validated")) if has_model else None,
            "reference_rmsd": reg_entry.get("reference_rmsd"),
            "enrichment_auc": reg_entry.get("enrichment_auc"),
            "test_r2": metrics.get("R2_Test"),
            "test_rmse": metrics.get("RMSE_Test"),
        })
    return out


def _confidence_label(rmsd):
    if rmsd is None:
        return None
    if rmsd < 1.0:
        return "Excellent"
    if rmsd < 1.5:
        return "Good"
    return "Acceptable"


def recommendation(target_id):
    """The full 'Why this?' evidence bundle for one target's recommended
       docking structure, or None if target_id isn't one of ours."""
    t2g, _ = _target_gene_map()
    gene = t2g.get(target_id)
    if gene is None:
        return None

    reg = load_registry()
    reg_entry = reg.get(target_id) or {}
    panel = panel_evidence(gene) or {}

    our_pdb_id = None
    src = reg_entry.get("pdb_source")
    if src:
        our_pdb_id = src.split("_raw")[0].split(".")[0].upper()

    rank = None
    panel_best = panel.get("best_pdb_id")
    if our_pdb_id and isinstance(panel.get("n_qualifying_structures"), (int, float)):
        # rank position of the structure we actually validated, among the
        # panel's own crystallographic ranking (1-indexed), if it's in there
        df = _panel_df()
        if df is not None:
            match = df[df["targetSymbol"] == gene]
            if not match.empty:
                ranked = str(match.iloc[0].get("all_pdb_ids_ranked") or "").split(";")
                if our_pdb_id in ranked:
                    rank = ranked.index(our_pdb_id) + 1

    validated = bool(reg_entry.get("validated"))
    rmsd = reg_entry.get("reference_rmsd")
    if validated and our_pdb_id:
        headline = f"Recommended structure: {our_pdb_id} — {_confidence_label(rmsd)} structural evidence"
    elif our_pdb_id:
        headline = f"No validated structure yet — last attempt ({our_pdb_id}) did not pass redocking"
    else:
        headline = "No validated structure yet for this target"

    return {
        "target_id": target_id,
        "gene": gene,
        "headline": headline,
        "our_validation": {
            "validated": validated,
            "pdb_id": our_pdb_id,
            "ligand_resname": reg_entry.get("reference_ligand_resname"),
            "reference_rmsd": rmsd,
            "enrichment_auc": reg_entry.get("enrichment_auc"),
            "enrichment_ef20": reg_entry.get("enrichment_ef20"),
            "enrichment_n": reg_entry.get("enrichment_n"),
            "rank_in_panel_evidence": rank,
        },
        "panel_evidence": {
            "top_ranked_pdb_id": panel_best,
            "top_ranked_chain": panel.get("best_chain"),
            "top_ranked_ligand": panel.get("ligand"),
            "resolution": panel.get("resolution"),
            "resolution_tier": panel.get("resolution_tier"),
            "r_free": panel.get("r_free"),
            "modeled_residues": panel.get("modeled_residues"),
            "ligand_RSCC": panel.get("ligand_RSCC"),
            "ligand_RSR": panel.get("ligand_RSR"),
            "n_qualifying_structures": panel.get("n_qualifying_structures"),
            "chembl_activity_records": panel.get("activity_records"),
            "note": ("Crystallographic quality context only — not proof Vina can redock it; "
                     "see our_validation for the actual empirical result."),
        },
    }
