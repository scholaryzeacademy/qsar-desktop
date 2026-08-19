"""
Ligand preparation: SMILES -> 3D conformer -> PDBQT.  [TESTED]

Uses RDKit (ETKDG embed + MMFF) and Meeko (permissive PDBQT writer).
The same standardiser as QSAR/ADMET is used so structures are consistent.
"""
from dataclasses import dataclass
from rdkit import Chem
from rdkit.Chem import AllChem

try:
    from meeko import MoleculePreparation, PDBQTWriterLegacy
    _MEEKO = True
except Exception:
    _MEEKO = False


@dataclass
class LigandPrep:
    smiles: str
    mol: object            # RDKit mol with a 3D conformer (H-added)
    pdbqt: str             # PDBQT text for docking engines
    ok: bool
    error: str = ""


def prepare_ligand(smiles, seeds=(0xf00d, 1, 42, 7)):
    m = Chem.MolFromSmiles(smiles)
    if m is None:
        return LigandPrep(smiles, None, "", False, "invalid SMILES")
    m = Chem.AddHs(m)
    params = AllChem.ETKDGv3()
    embedded = -1
    for s in seeds:                       # retry embedding on strained natural products
        params.randomSeed = int(s)
        if AllChem.EmbedMolecule(m, params) == 0:
            embedded = 0; break
    if embedded != 0:
        if AllChem.EmbedMolecule(m, useRandomCoords=True) != 0:
            return LigandPrep(smiles, None, "", False, "3D embedding failed")
    try:
        AllChem.MMFFOptimizeMolecule(m)
    except Exception:
        pass
    pdbqt = ""
    if _MEEKO:
        try:
            prep = MoleculePreparation()
            setups = prep.prepare(m)
            out = PDBQTWriterLegacy.write_string(setups[0])
            pdbqt = out[0] if isinstance(out, tuple) else out
        except Exception as e:
            return LigandPrep(smiles, m, "", False, f"Meeko PDBQT failed: {e}")
    return LigandPrep(smiles, m, pdbqt, True)