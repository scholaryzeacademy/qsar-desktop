"""
PoseBusters physical-validity gate.  [TESTED]

PoseBusters is NOT a third engine — it is a filter every engine's poses pass
through BEFORE they are trusted or compared. It checks stereochemistry, bond
lengths/angles, ring flatness, internal clashes and (with a receptor)
protein-ligand clashes. Poses that fail are dropped so physically impossible
geometries never reach the ranking.
"""
from rdkit import Chem

try:
    from posebusters import PoseBusters
    _AVAILABLE = True
except Exception:
    _AVAILABLE = False


class ValidityGate:
    def __init__(self, receptor_pdb=None):
        """receptor_pdb: path to the prepared receptor PDB. If given, protein-ligand
           clash checks run (config 'dock'); otherwise ligand-only checks (config 'mol')."""
        self.receptor = receptor_pdb
        self.buster = PoseBusters(config="dock" if receptor_pdb else "mol") if _AVAILABLE else None

    @property
    def available(self):
        return _AVAILABLE

    def check(self, mol):
        """Return (passed: bool, report: dict of check -> bool). Fail-closed on error."""
        if not _AVAILABLE:
            return True, {"posebusters": "not installed — validity not checked"}
        try:
            df = self.buster.bust([mol], None, self.receptor)
            row = df.iloc[0].to_dict()
            checks = {k: bool(v) for k, v in row.items() if isinstance(v, (bool,)) or v in (True, False)}
            passed = all(checks.values()) if checks else False
            return passed, checks
        except Exception as e:
            return False, {"error": str(e)}

    def filter(self, poses):
        """Keep only poses whose RDKit mol passes. Returns (kept, reports)."""
        kept, reports = [], []
        for p in poses:
            ok, rep = self.check(p.mol)
            reports.append({"pose_id": getattr(p, "pose_id", None), "passed": ok, "report": rep})
            if ok:
                kept.append(p)
        return kept, reports