"""
Atom-map-safe cross-engine RMSD.  [TESTED]

THE TRAP (from the docking spec review): atom ordering is NOT guaranteed
identical across Vina and AutoDock4 outputs. A naive index-wise RMSD then
compares mismatched atoms and silently returns a garbage number, which
quietly corrupts the whole consensus/confidence signal.

FIX: (1) hard-assert the two poses are the SAME molecule (same heavy-atom
graph) before comparing; (2) use RDKit GetBestRMS, which finds the correct
atom mapping over molecular symmetry rather than trusting index order.
"""
from rdkit import Chem
from rdkit.Chem import rdMolAlign


def _heavy_graph_smiles(mol):
    m = Chem.RemoveHs(Chem.Mol(mol))
    m = Chem.Mol(m)
    Chem.RemoveStereochemistry(m)              # docked poses may not carry stereo
    return Chem.MolToSmiles(m)


def same_molecule(a, b):
    return _heavy_graph_smiles(a) == _heavy_graph_smiles(b)


def safe_rmsd(pose_a, pose_b):
    """Heavy-atom best-fit RMSD between two poses of the SAME molecule.
       Raises ValueError if they are not the same molecule (never returns a
       misleading number). Works on copies; does not mutate inputs."""
    if pose_a is None or pose_b is None:
        raise ValueError("safe_rmsd: a pose is None")
    a = Chem.RemoveHs(Chem.Mol(pose_a))
    b = Chem.RemoveHs(Chem.Mol(pose_b))
    if a.GetNumAtoms() != b.GetNumAtoms() or not same_molecule(a, b):
        raise ValueError("safe_rmsd: poses are not the same molecule — atom mapping "
                         "would be invalid; refusing to return an RMSD.")
    # GetBestRMS handles symmetry and finds the correct mapping (not index order)
    return float(rdMolAlign.GetBestRMS(Chem.Mol(b), Chem.Mol(a)))


def rmsd_matrix(poses_a, poses_b):
    """Full pairwise heavy-atom RMSD; None where the pair isn't the same molecule."""
    out = []
    for pa in poses_a:
        row = []
        for pb in poses_b:
            try:
                row.append(round(safe_rmsd(pa, pb), 3))
            except ValueError:
                row.append(None)
        out.append(row)
    return out