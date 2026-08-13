"""
Pick which protein chain to restrict receptor prep to.

Real PDB depositions very often carry 2+ copies of the same protein (a
crystallographic dimer in the asymmetric unit, not a biological complex) —
1IEP/ABL1 is a concrete example already in this repo's registry. Feeding
receptor_prep.py both copies works for the receptor itself, but
scripts/validate_target.py's crystal-ligand extraction grabs every instance
of the reference ligand's resname across ALL chains, which — when there are
2+ — corrupts AssignBondOrdersFromTemplate into a nonsense 2-fragment mol
and makes safe_rmsd() correctly refuse to score it (see rmsd.py). Confirmed
against 1IEP: chains A and B both carry a full copy of STI.

Restricting to ONE chain (whichever actually carries the reference ligand;
first alphabetically if several identical copies do) reproduces the correct
single-copy geometry receptor_prep.py's own docstring already recommends.
"""
from Bio.PDB import PDBParser

COMMON_ADDITIVES = {"HOH", "WAT", "SO4", "PO4", "GOL", "EDO", "PEG", "ACT", "NA",
                    "CL", "K", "MG", "ZN", "CA", "MN", "DMS", "TRS", "FMT", "IOD"}


def chain_for_ligand(pdb_path, resname):
    """Returns the (alphabetically first) chain id that contains a HETATM
       group named `resname`, or None if it isn't found anywhere."""
    s = PDBParser(QUIET=True).get_structure("x", pdb_path)
    chains_with_ligand = set()
    for model in s:
        for ch in model:
            for res in ch:
                if res.id[0].strip() and res.resname.strip() == resname:
                    chains_with_ligand.add(ch.id)
        break
    if not chains_with_ligand:
        return None
    return sorted(chains_with_ligand)[0]
