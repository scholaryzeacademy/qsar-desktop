"""
Generic per-target docking validation pipeline.  [orchestration WRITTEN — validated for CHEMBL1862_ABL1/1IEP, see docking_registry.json]

Generalizes the one-off cox2 recipe (receptor_prep.py + make_rcx.py +
validate_cox2.py + enrichment_test.py, all previously hand-run for a single
target) into one reusable script driven by target_id + a real PDB entry:

    1. Download the PDB structure from RCSB (real experimental structure).
    2. Prepare the receptor (strip/repair/PDBQT) via docking/receptor_prep.py.
    3. Fetch the co-crystallised ligand's real SMILES from RCSB's Chemical
       Component Dictionary, and extract its crystal pose to an SDF.
    4. Reference redocking: does Vina reproduce the crystal pose? (RMSD gate —
       this is what actually flips 'validated' in docking_registry.json.)
    5. Enrichment test: does Vina's score rank this target's own most-potent
       real ChEMBL training compounds above its least-potent ones? Recorded
       for transparency regardless of how it turns out — it does NOT gate
       'validated' (weak ranking on a handful of compounds doesn't mean the
       geometry is wrong, and a strong showing here doesn't replace RMSD proof).

    IMPORTANT HONESTY NOTE: the "decoys" here are this target's own weakest-
    measured real ChEMBL compounds, not confirmed non-binders (a true DUD-E-
    style decoy set would need external tooling this project doesn't have).
    That's still a real, grounded comparison — "does docking score correlate
    with real measured potency" — just a different (arguably harder) one than
    active-vs-non-binder. Recorded in the registry as 'enrichment_source' so
    nobody mistakes it for the cox2 entry's curated true-decoy methodology.

Usage:
    python scripts/validate_target.py <target_id> <pdb_id> <ligand_resname> [options]

Example (the pilot run this was validated against):
    python scripts/validate_target.py CHEMBL1862_ABL1 1IEP STI
"""
import argparse
import json
import os
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

from docking import receptor_prep
from docking import profile as P
from docking import pipeline
from docking.profile import REGISTRY
from scripts.enrichment_test import dock_scores, metrics, verdict


def fetch_pdb(pdb_id, out_path):
    url = f"https://files.rcsb.org/download/{pdb_id}.pdb"
    urllib.request.urlretrieve(url, out_path)
    return out_path


def fetch_ligand_smiles(resname):
    url = f"https://data.rcsb.org/rest/v1/core/chemcomp/{resname}"
    with urllib.request.urlopen(url, timeout=20) as r:
        d = json.load(r)
    descs = d.get("pdbx_chem_comp_descriptor", [])
    for want in ("SMILES_CANONICAL", "SMILES"):
        for entry in descs:
            if entry.get("type") == want:
                return entry["descriptor"]
    raise RuntimeError(f"RCSB has no SMILES on record for ligand '{resname}'")


def make_crystal_sdf(raw_pdb, resname, out_sdf, template_smiles, chain=None):
    """Extract just the co-crystallised ligand's real docked pose to an SDF,
       for RMSD comparison against Vina's redocked pose (see make_rcx.py, the
       one-off precedent this generalizes).

       Chem.MolFromPDBFile only has 3D coordinates to go on — it guesses bonds
       from interatomic distances and frequently gets bond ORDERS wrong (e.g.
       aromatic rings, double bonds), even when the atom connectivity itself
       is right. safe_rmsd() correctly refuses to compare a wrongly-perceived
       molecule against the real one (that's the point of it being atom-map-
       safe), so this reassigns correct bond orders from the ligand's real
       SMILES (already fetched from RCSB) onto the crystal coordinates via
       AssignBondOrdersFromTemplate — standard practice for crystal ligands."""
    from rdkit import Chem
    from rdkit.Chem import AllChem
    from Bio.PDB import PDBParser, PDBIO, Select

    class OnlyRes(Select):
        def accept_residue(self, res):
            if res.resname.strip() != resname:
                return False
            if chain and res.get_parent().id != chain:
                return False
            return True

    s = PDBParser(QUIET=True).get_structure("x", raw_pdb)
    io = PDBIO()
    io.set_structure(s)
    tmp_pdb = out_sdf + ".tmp.pdb"
    io.save(tmp_pdb, OnlyRes())
    raw = Chem.MolFromPDBFile(tmp_pdb, removeHs=True)
    os.remove(tmp_pdb)
    if raw is None:
        raise RuntimeError(f"RDKit could not parse extracted ligand '{resname}' from {raw_pdb} "
                            f"(bond perception from distances failed — check the resname is right)")
    template = Chem.MolFromSmiles(template_smiles)
    if template is None:
        raise RuntimeError(f"could not parse template SMILES for '{resname}': {template_smiles}")
    try:
        m = AllChem.AssignBondOrdersFromTemplate(template, raw)
    except ValueError as e:
        raise RuntimeError(f"crystal ligand '{resname}' atom connectivity doesn't match its real "
                            f"SMILES template ({e}) — the PDB deposition may be missing atoms, or "
                            f"the resname/ligand identity may be wrong") from e
    Chem.MolToMolFile(m, out_sdf)
    return out_sdf


def build_enrichment_rows(target_id, n_side):
    """This target's own real ChEMBL training compounds: the n_side most potent
       (by measured pchembl_value) as 'active', the n_side least potent as
       'decoy' — see the honesty note in the module docstring."""
    csv_path = os.path.join("models", target_id, "Data", "full_cleaned.csv")
    df = pd.read_csv(csv_path).dropna(subset=["smiles", "pchembl_value"])
    df = df.sort_values("pchembl_value", ascending=False)
    top, bottom = df.head(n_side), df.tail(n_side)
    rows = ([{"name": r.chembl_id, "smiles": r.smiles, "label": "active"} for r in top.itertuples()] +
            [{"name": r.chembl_id, "smiles": r.smiles, "label": "decoy"} for r in bottom.itertuples()])
    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("target_id", help="QSAR target folder name, e.g. CHEMBL1862_ABL1")
    ap.add_argument("pdb_id", help="RCSB PDB entry with the co-crystallised ligand, e.g. 1IEP")
    ap.add_argument("ligand_resname", help="3-5 char ligand code in that PDB entry, e.g. STI")
    ap.add_argument("--chain", default=None)
    ap.add_argument("--n-side", type=int, default=8, help="actives/decoys per side (default 8, matches cox2's n=16)")
    ap.add_argument("--rmsd-threshold", type=float, default=2.0)
    args = ap.parse_args()

    tdir = os.path.join("docking_targets", args.target_id)
    os.makedirs(tdir, exist_ok=True)
    raw_pdb = os.path.join(tdir, f"{args.pdb_id}_raw.pdb")

    print(f"[1/5] downloading {args.pdb_id} from RCSB ...")
    fetch_pdb(args.pdb_id, raw_pdb)

    print("[2/5] preparing receptor (strip -> PDBFixer repair -> Meeko PDBQT) ...")
    receptor_prep.prepare_receptor(raw_pdb, args.target_id, ref_resname=args.ligand_resname, chain=args.chain)

    print(f"[3/5] fetching real SMILES for ligand '{args.ligand_resname}' + extracting crystal pose ...")
    lig_smiles = fetch_ligand_smiles(args.ligand_resname)
    crystal_sdf = make_crystal_sdf(raw_pdb, args.ligand_resname, os.path.join(tdir, "crystal_ligand.sdf"),
                                    lig_smiles, chain=args.chain)
    print("    ligand SMILES:", lig_smiles)

    print("[4/5] reference redocking (does Vina reproduce the crystal pose?) ...")
    prof = P.load_profile(args.target_id)
    redock = pipeline.redock_reference(prof, lig_smiles, crystal_sdf=crystal_sdf, rmsd_threshold=args.rmsd_threshold)
    print("   ", redock)
    rmsd, validated = redock.get("reference_rmsd"), bool(redock.get("validated"))

    n_total = 2 * args.n_side
    print(f"[5/5] enrichment test ({n_total} real compounds from this target's own training data) ...")
    rows = build_enrichment_rows(args.target_id, args.n_side)
    scored = dock_scores(args.target_id, rows)
    m = metrics(scored)
    print("    AUC:", m.get("auc"), "  EF@20%:", m.get("ef_top"), "  verdict:", verdict(m))

    reg = json.load(open(REGISTRY))
    for t in reg["targets"]:
        if t["target_id"] == args.target_id:
            t["validated"] = validated
            t["reference_rmsd"] = rmsd
            t["enrichment_auc"] = m.get("auc")
            t["enrichment_ef20"] = m.get("ef_top")
            t["enrichment_n"] = m.get("n_docked")
            t["enrichment_source"] = ("own ChEMBL training data: top/bottom "
                                       f"{args.n_side} by measured pchembl_value — "
                                       "'decoys' are this target's weakest measured "
                                       "binders, not confirmed non-binders")
    json.dump(reg, open(REGISTRY, "w"), indent=2)
    print(f"\ndone. registry updated for '{args.target_id}': validated = {validated}")
    if not validated:
        print(f"NOT validated: reference RMSD {rmsd} A exceeds the {args.rmsd_threshold} A threshold "
              f"(or redocking failed) — Screen/Docking will keep skipping this target until it passes.")


if __name__ == "__main__":
    main()
