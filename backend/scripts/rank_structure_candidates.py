"""Pull + rank the 'Manual structure' candidate list (Advanced Settings'
override picker) for EVERY protein target in panel_results_v2.csv — both our
~52 QSAR-modeled targets and the ~600+ targets with no QSAR model
(GENE_<symbol>-only, docking-only in the UI).

This is the exact same candidate set/ranking app.py's
/api/targets/{id}/structure_candidates and /api/genes/{gene}/structure_candidates
endpoints compute per-request (see app.py's _structure_candidates_for_gene) —
this script just runs it for the whole panel at once and writes it to disk,
so you can review coverage (which genes have a usable manual override and
which don't) without clicking through every target in the UI one at a time.

Cheap tier only (top5_pdb_summary, no live RCSB calls) — matches what the UI
picker itself shows; scripts.panel_candidates.candidates_from_panel's
extra_limit tier (live lookups beyond the top 5) is NOT used here, to keep
this a fast, no-network, re-runnable report.

Usage: python -m scripts.rank_structure_candidates
Writes:
  structure_candidates_ranked.csv  — one row per (gene, ranked candidate)
  structure_candidates_gaps.csv    — one row per gene with ZERO usable
                                      candidates despite n_qualifying_structures > 0
                                      (top-5-only + ligand-blacklist filtering
                                      excluded everything — see panel_candidates.py)
"""
import csv
import os
import re
import sys

from scripts import panel_candidates as PC
from scripts.batch_validate import gene_for_target, usable_targets
from docking.profile import load_registry

QUALITY_RE = re.compile(r"^(\S+)\s+\(res=([\d.]+),\s*RSCC=([\d.]+),\s*RSR=([\d.]+)\)")


def _target_gene_map():
    t2g = {tid: gene_for_target(tid) for tid in usable_targets()}
    g2t = {g: t for t, g in t2g.items()}
    return t2g, g2t


def _default_pdb_for(target_id, reg):
    src = (reg.get(target_id) or {}).get("pdb_source")
    if not src:
        return None
    return src.split("_raw")[0].split(".")[0].upper()


def candidates_for_gene(gene, default_pdb=None):
    """Same logic as app.py's _structure_candidates_for_gene, standalone
       (no FastAPI/app.py import, so this stays fast and dependency-light)."""
    df = PC._panel_df()
    if df is None or gene not in df.index:
        return [], None
    row = df.loc[gene]
    ranked_ids = [p for p in str(row.get("all_pdb_ids_ranked") or "").split(";") if p]
    cands = PC._parse_top5(row.get("top5_pdb_summary"))

    quality_by_pdb = {}
    for chunk in str(row.get("top5_pdb_summary") or "").split(" | "):
        m = QUALITY_RE.match(chunk.strip())
        if m:
            quality_by_pdb[m.group(1)] = {"resolution": float(m.group(2)), "ligand_RSCC": float(m.group(3)),
                                          "ligand_RSR": float(m.group(4))}
    out = []
    for c in cands:
        try:
            rank = ranked_ids.index(c["pdb_id"]) + 1
        except ValueError:
            rank = None
        q = quality_by_pdb.get(c["pdb_id"], {})
        out.append({"pdb_id": c["pdb_id"], "resname": c["resname"], "csv_rank": rank,
                    "is_current_default": c["pdb_id"] == default_pdb,
                    "resolution": q.get("resolution"), "ligand_RSCC": q.get("ligand_RSCC"),
                    "ligand_RSR": q.get("ligand_RSR")})
    return out, row.get("n_qualifying_structures")


def main():
    df = PC._panel_df()
    if df is None:
        sys.exit(f"panel CSV not found: {PC.PANEL_CSV}")

    _, g2t = _target_gene_map()
    reg = load_registry()

    ranked_rows = []
    gap_rows = []
    genes = sorted(df.index.unique())
    for gene in genes:
        target_id = g2t.get(gene)
        default_pdb = _default_pdb_for(target_id, reg) if target_id else None
        candidates, n_qualifying = candidates_for_gene(gene, default_pdb)
        for i, c in enumerate(candidates, start=1):
            ranked_rows.append({
                "gene": gene, "target_id": target_id or "", "has_qsar_model": bool(target_id),
                "rank_in_manual_list": i, **c, "n_qualifying_structures": n_qualifying,
            })
        if not candidates and (n_qualifying or 0) > 0:
            gap_rows.append({"gene": gene, "target_id": target_id or "", "has_qsar_model": bool(target_id),
                             "n_qualifying_structures": n_qualifying})

    ranked_path = "structure_candidates_ranked.csv"
    with open(ranked_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["gene", "target_id", "has_qsar_model", "rank_in_manual_list",
                                          "pdb_id", "resname", "csv_rank", "is_current_default",
                                          "resolution", "ligand_RSCC", "ligand_RSR", "n_qualifying_structures"])
        w.writeheader()
        w.writerows(ranked_rows)

    gaps_path = "structure_candidates_gaps.csv"
    with open(gaps_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["gene", "target_id", "has_qsar_model", "n_qualifying_structures"])
        w.writeheader()
        w.writerows(gap_rows)

    n_model = sum(1 for g in genes if g in g2t)
    n_with_candidates = len({r["gene"] for r in ranked_rows})
    print(f"{len(genes)} genes total ({n_model} with a QSAR model, {len(genes) - n_model} docking-only)")
    print(f"{n_with_candidates} genes have >=1 manual-structure candidate ({len(ranked_rows)} candidate rows) -> {ranked_path}")
    print(f"{len(gap_rows)} genes have qualifying structures in the CSV but NONE survive the top-5/ligand filter -> {gaps_path}")


if __name__ == "__main__":
    main()
