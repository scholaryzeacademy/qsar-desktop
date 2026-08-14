"""
Docking engine (Vina) + GNINA CNN rescorer.
[VinaEngine + GNINA subprocess UNVALIDATED in dev; pure-Python helpers TESTED]

AutoDock4 has been removed (GPL, and a second physics scorer adds little over
Vina for ranking). The independent second opinion is now GNINA — a CNN rescorer
(Apache-licensed) that catches unphysical poses a docking score ranks too highly.
"""
import os, re, shutil, subprocess, tempfile
from dataclasses import dataclass, field
from rdkit import Chem


@dataclass
class Pose:
    engine: str
    score: float                     # kcal/mol (more negative = better)
    mol: object                      # RDKit mol (heavy atoms) with the pose conformer
    pose_id: str = ""
    meta: dict = field(default_factory=dict)


class DockingEngine:
    name = "base"
    def available(self) -> bool: raise NotImplementedError
    def dock(self, receptor_profile, ligand_prep, n_poses=9): raise NotImplementedError


# ---------- PDBQT -> RDKit ----------
def _split_conformers(mol):
    """Meeko's RDKitMolCreate merges every pose in a multi-MODEL PDBQT into ONE
       RDKit Mol carrying one conformer per pose (Vina writes poses best-to-worst,
       so conformer order matches --num_modes rank), rather than one Mol per pose.
       Split it into independent single-conformer Mols so downstream code (which
       treats each list entry as one distinct pose — PoseBusters filtering, RMSD
       self-consistency, the 3D pose export) actually sees all of them instead of
       silently only ever operating on one. A no-op for already-single-conformer
       input (e.g. the obabel/SDF fallback below)."""
    out = []
    for conf in mol.GetConformers():
        m2 = Chem.Mol(mol)
        m2.RemoveAllConformers()
        m2.AddConformer(Chem.Conformer(conf), assignId=True)
        out.append(m2)
    return out


def _pdbqt_file_to_rdkit(path):
    try:
        from meeko import PDBQTMolecule, RDKitMolCreate
        pm = PDBQTMolecule.from_file(path, skip_typing=True)
        out = RDKitMolCreate.from_pdbqt_mol(pm)
        mols = out[0] if isinstance(out, tuple) else out
        poses = []
        for m in mols:
            if m is not None:
                poses.extend(_split_conformers(m))
        return poses
    except Exception:
        sdf = path + ".sdf"
        subprocess.run(["obabel", path, "-O", sdf], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return [m for m in Chem.SDMolSupplier(sdf, removeHs=False) if m is not None]


# ---------- Vina ----------
class VinaEngine(DockingEngine):
    name = "vina"

    def __init__(self, binary="vina", exhaustiveness=8, cpu=None):
        """cpu: threads Vina's OWN internal search may use (its --cpu flag).
           Left at Vina's default (all detected cores) unless set — pass a
           capped value when running several VinaEngine.dock() calls
           CONCURRENTLY from different threads (see docking/enrichment.py's
           fresh_decoy_validation), so N parallel single-core-greedy Vina
           processes don't all independently try to grab every core and
           thrash each other for no wall-clock benefit."""
        self.binary, self.exhaustiveness, self.cpu = binary, exhaustiveness, cpu

    def available(self):
        return shutil.which(self.binary) is not None

    def dock(self, receptor_profile, ligand_prep, n_poses=9):
        if not self.available():
            raise RuntimeError("vina binary not found on PATH")
        cx, cy, cz = receptor_profile["center"]; sx, sy, sz = receptor_profile["box_size"]
        with tempfile.TemporaryDirectory() as td:
            lig = os.path.join(td, "lig.pdbqt"); out = os.path.join(td, "out.pdbqt")
            open(lig, "w").write(ligand_prep.pdbqt)
            cmd = [self.binary, "--receptor", receptor_profile["receptor_pdbqt"],
                  "--ligand", lig, "--center_x", str(cx), "--center_y", str(cy),
                  "--center_z", str(cz), "--size_x", str(sx), "--size_y", str(sy),
                  "--size_z", str(sz), "--out", out, "--num_modes", str(n_poses),
                  "--exhaustiveness", str(self.exhaustiveness)]
            if self.cpu:
                cmd += ["--cpu", str(self.cpu)]
            subprocess.run(cmd, check=True, capture_output=True, text=True)
            scores = [float(m) for m in re.findall(r"REMARK VINA RESULT:\s+([-\d.]+)", open(out).read())]
            mols = _pdbqt_file_to_rdkit(out)
        return [Pose("vina", scores[i] if i < len(scores) else float("nan"),
                     Chem.RemoveHs(m), f"vina_{i+1}") for i, m in enumerate(mols)]


# ---------- GNINA CNN rescorer (second opinion) ----------
def parse_gnina(stdout):
    """Extract CNNscore, CNNaffinity, and Vina-style Affinity from gnina --score_only output."""
    def g(pat):
        m = re.search(pat, stdout)
        return float(m.group(1)) if m else None
    return {"cnn_score": g(r"CNNscore:\s*([-\d.]+)"),
            "cnn_affinity": g(r"CNNaffinity:\s*([-\d.]+)"),
            "gnina_affinity": g(r"Affinity:\s*([-\d.]+)")}


class NullRescorer:
    """Always-unavailable rescorer — lets a caller force GNINA off (Advanced
       Settings 'disable rescoring') without an if/else at every call site."""
    name = "gnina"
    def available(self): return False
    def rescore(self, receptor_pdb, pose_mol): return None


class GninaRescorer:
    """CNN pose rescoring. CNNscore (0-1) = pose-quality confidence; CNNaffinity = predicted pKd-like."""
    name = "gnina"

    def __init__(self, binary="gnina"):
        self.binary = binary

    def available(self):
        return shutil.which(self.binary) is not None

    def rescore(self, receptor_pdb, pose_mol):
        if not self.available():
            return None
        with tempfile.TemporaryDirectory() as td:
            lig_sdf = os.path.join(td, "pose.sdf")
            w = Chem.SDWriter(lig_sdf); w.write(pose_mol); w.close()
            try:
                r = subprocess.run([self.binary, "-r", receptor_pdb, "-l", lig_sdf, "--score_only"],
                                   check=True, capture_output=True, text=True)
            except Exception as e:
                return {"error": str(e)}
            return parse_gnina(r.stdout)