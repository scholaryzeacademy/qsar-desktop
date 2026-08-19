from rdkit import Chem
from Bio.PDB import PDBParser, PDBIO, Select

class RCXonly(Select):
    def accept_residue(self, r):
        return r.resname.strip() == "RCX"

s = PDBParser(QUIET=True).get_structure("x", "5kir.pdb")
io = PDBIO()
io.set_structure(s)
io.save("rcx_crystal.pdb", RCXonly())

m = Chem.MolFromPDBFile("rcx_crystal.pdb", removeHs=True)
print("RCX atoms parsed:", m.GetNumAtoms() if m else "FAILED")
if m:
    Chem.MolToMolFile(m, "rcx_crystal.sdf")
    print("wrote rcx_crystal.sdf")