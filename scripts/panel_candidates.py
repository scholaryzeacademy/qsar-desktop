"""CSV-driven candidate source for docking receptor onboarding.

Sourced from panel_results_v2.csv's pre-vetted structural-quality ranking
(resolution, ligand RSCC/RSR against `all_pdb_ids_ranked` /
`top5_pdb_summary`) instead of scripts/select_receptor.py's live
UniProt/RCSB lookups — much richer candidate pools for the same gene
(e.g. ABL1 has 43 qualifying structures in the CSV vs. the handful
select_receptor.py's live search typically surfaces), at the cost of a
static snapshot rather than the current PDB state.

The CSV's own "best" pick is NOT trustworthy on its own: it's ranked by
crystallographic quality (resolution/RSCC/RSR), not by whether the bound
ligand is even a real inhibitor. Example: PDGFRB's top-ranked structure
(3MJG) only has glycosylation sugars (NDG/NAG) as ligands. So every
candidate ligand is filtered through the same
scripts/select_receptor.ADDITIVE_BLACKLIST (+ MW floor) used for live
candidates, before being trusted.

This does NOT decide 'validated' — same contract as select_receptor.py:
it only proposes (pdb_id, resname) pairs for scripts/validate_target.py
to actually prepare + redock + RMSD-check.
"""
import functools
import os
import re

import pandas as pd

from scripts.select_receptor import ADDITIVE_BLACKLIST, best_ligand_for_entry

PANEL_CSV = os.environ.get("PANEL_RESULTS_CSV", "panel_results_v2.csv")
MIN_LIGAND_MW = 180.0   # matches select_receptor.py's cryoprotectant/buffer floor

_ENTRY_RE = re.compile(r"^(\S+)\s+\(res=[^)]*\)\s+ligands:\s*(.*)$")
_LIG_RE = re.compile(r"([A-Za-z0-9]{1,5})=[^;]*?\((\d+(?:\.\d+)?)\s*Da\)")


@functools.lru_cache(maxsize=1)
def _panel_df():
    if not os.path.exists(PANEL_CSV):
        return None
    df = pd.read_csv(PANEL_CSV)
    return df.drop_duplicates(subset=["targetSymbol"], keep="first").set_index("targetSymbol")


def _best_ligand_from_text(ligand_text):
    """'RES1=desc (MW Da) [source]; RES2=...' -> (resname, mw) for the
       largest ligand not in ADDITIVE_BLACKLIST, or None."""
    best = None
    for m in _LIG_RE.finditer(ligand_text or ""):
        resname, mw = m.group(1).upper(), float(m.group(2))
        if resname in ADDITIVE_BLACKLIST or mw < MIN_LIGAND_MW:
            continue
        if best is None or mw > best[1]:
            best = (resname, mw)
    return best


def _parse_top5(top5_summary):
    """top5_pdb_summary text -> ordered [{pdb_id, resname}], real-inhibitor
       filtered. Entries whose only ligands are additives/sugars are
       skipped entirely (this is what fixes PDGFRB/3MJG)."""
    out = []
    if not isinstance(top5_summary, str):
        return out
    for chunk in top5_summary.split(" | "):
        m = _ENTRY_RE.match(chunk.strip())
        if not m:
            continue
        pdb_id, ligand_text = m.group(1), m.group(2)
        best = _best_ligand_from_text(ligand_text)
        if best:
            out.append({"pdb_id": pdb_id, "resname": best[0]})
    return out


def candidates_from_panel(gene_symbol, extra_limit=0, exclude=None):
    """Ordered [{pdb_id, resname, csv_rank}] for gene_symbol from the panel
    CSV. csv_rank is this candidate's 1-indexed position in the CSV's own
    `all_pdb_ids_ranked` column — kept on every candidate so callers can log
    which Version 2 CSV rank a receptor pick actually came from.

    Cheap tier (default): candidates from top5_pdb_summary only, ligand
    already known from the CSV text, no network calls.

    extra_limit>0: additionally resolves up to that many further entries
    from all_pdb_ids_ranked (beyond the top5) via a live RCSB lookup per
    entry (select_receptor.best_ligand_for_entry) — meant to be called
    by the caller only after the cheap tier + live select_receptor
    candidates are all exhausted, to avoid unnecessary API calls for
    targets that validate on the first try.
    """
    df = _panel_df()
    if df is None or gene_symbol not in df.index:
        return []
    row = df.loc[gene_symbol]
    exclude = set(exclude or ())
    ranked_ids = [p for p in str(row.get("all_pdb_ids_ranked") or "").split(";") if p]

    def _rank(pdb_id):
        try:
            return ranked_ids.index(pdb_id) + 1
        except ValueError:
            return None

    out = [dict(c, csv_rank=_rank(c["pdb_id"]))
           for c in _parse_top5(row.get("top5_pdb_summary")) if c["pdb_id"] not in exclude]

    if extra_limit > 0:
        seen = exclude | {c["pdb_id"] for c in out}
        extra_ids = [p for p in ranked_ids if p not in seen][:extra_limit]
        for pdb_id in extra_ids:
            try:
                lig = best_ligand_for_entry(pdb_id)
            except Exception:
                continue
            if lig:
                out.append({"pdb_id": pdb_id, "resname": lig[0], "csv_rank": _rank(pdb_id)})
    return out


def panel_evidence(gene_symbol):
    """Structural-quality context for a gene's panel-CSV row, for the
       'Why this?' evidence view — raw fields, no filtering/opinions."""
    df = _panel_df()
    if df is None or gene_symbol not in df.index:
        return None
    row = df.loc[gene_symbol]
    return {
        "best_pdb_id": row.get("best_pdb_id"),
        "best_chain": row.get("best_chain"),
        "ligand": row.get("ligand"),
        "resolution": row.get("resolution"),
        "resolution_tier": row.get("resolution_tier"),
        "r_free": row.get("r_free"),
        "modeled_residues": row.get("modeled_residues"),
        "ligand_RSCC": row.get("ligand_RSCC"),
        "ligand_RSR": row.get("ligand_RSR"),
        "n_qualifying_structures": row.get("n_qualifying_structures"),
        "chembl_target_ids": row.get("chembl_target_ids"),
        "activity_records": row.get("activity_records"),
    }
