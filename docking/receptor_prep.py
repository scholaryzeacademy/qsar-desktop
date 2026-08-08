"""
Receptor preparation (build-time, once per target).  [WRITTEN â VALIDATE ON YOUR MACHINE]

raw PDB (with co-crystallised ligand)
  -> extract reference ligand            (Bio.PDB)
  -> strip waters/HETATMs                (Bio.PDB)
  -> repair: add missing atoms + H       (PDBFixer / OpenMM)
  -> grid box from reference ligand      (grid_box_from_ligand â TESTED math)
  -> receptor PDBQT                       (Meeko mk_prepare_receptor)
  -> save DockingProfile to docking_registry.json

!! I could not execute this end-to-end (PDBFixer/real PDBs unavailable
   in development). The pure-Python parts (ligand extraction, box math, .gpf text)
   are tested; the external-tool steps are standard but UNVALIDATED. VALIDATE by
   re-docking the co-crystallised ligand and confirming RMSD < ~2 A before trusting
   any result for this target.

Dependencies (install on your machine):
   conda install -c conda-forge pdbfixer openmm
   pip install meeko                      # provides mk_prepare_receptor
"""
import os, json, shutil, subprocess, tempfile
import numpy as np

from .profile import grid_box_from_ligand, REGISTRY

COMMON_ADDITIVES = {"HOH", "WAT", "SO4", "PO4", "GOL", "EDO", "PEG", "ACT", "NA",
                    "CL", "K", "MG", "ZN", "CA", "MN", "DMS", "TRS", "FMT", "IOD"}


# ---------- step 1: parse + extract reference ligand ----------
def extract_reference_ligand(pdb_path, ref_resname=None, chain=None):
    """Return (ref_ligand_coords Nx3, ref_resname, ref_atoms) for the co-crystallised
       inhibitor. If ref_resname is None, pick the largest non-additive HETATM group."""
    from Bio.PDB import PDBParser
    s = PDBParser(QUIET=True).get_structure("x", pdb_path)
    candidates = {}
    for model in s:
        for ch in model:
            if chain and ch.id != chain:
                continue
            for res in ch:
                het = res.id[0].strip()               # '' for standard, 'H_XXX'/'W' for hetero
                if not het:
                    continue
                name = res.resname.strip()
                if name in COMMON_ADDITIVES:
                    continue
                if ref_resname and name != ref_resname:
                    continue
                coords = np.array([a.coord for a in res.get_atoms()], float)
                key = (name, ch.id, res.id[1])
                candidates[key] = coords
        break                                          # first model only
    if not candidates:
        raise ValueError("no reference ligand found (check ref_resname / additives list)")
    # largest heavy-atom group wins (deterministic)
    key = max(candidates, key=lambda k: len(candidates[k]))
    return candidates[key], key[0], candidates[key].shape[0]


# ---------- step 2: strip to protein only ----------
def strip_to_protein(pdb_path, out_pdb, chain=None):
    """Standard residues only (no HETATM/water). If chain is given, keep ONLY
       that chain — many PDB entries deposit 2+ copies of the same protein in
       the asymmetric unit (e.g. a crystallographic dimer), and merging them
       into one 'receptor' both docks against a physically wrong target (two
       overlapping copies) and can confuse bond-perception in atoms close to
       the chain-chain interface (RDKit inferring spurious cross-chain bonds)."""
    from Bio.PDB import PDBParser, PDBIO, Select

    class ProteinOnly(Select):
        def accept_residue(self, res):
            if res.id[0] != " ":
                return False
            if chain and res.get_parent().id != chain:
                return False
            return True

    s = PDBParser(QUIET=True).get_structure("x", pdb_path)
    io = PDBIO(); io.set_structure(s)
    io.save(out_pdb, ProteinOnly())
    return out_pdb


# ---------- step 3: repair (PDBFixer) ----------
def repair_receptor(pdb_in, pdb_out, ph=7.0):
    try:
        from pdbfixer import PDBFixer
        from openmm.app import PDBFile
    except Exception as e:
        raise RuntimeError(f"PDBFixer/OpenMM not installed: {e}. "
                           f"conda install -c conda-forge pdbfixer openmm")
    fixer = PDBFixer(filename=pdb_in)
    fixer.findMissingResidues()
    fixer.findNonstandardResidues()
    fixer.replaceNonstandardResidues()
    fixer.removeHeterogens(keepWater=False)
    fixer.findMissingAtoms()
    fixer.addMissingAtoms()
    fixer.addMissingHydrogens(ph)
    with open(pdb_out, "w") as f:
        PDBFile.writeFile(fixer.topology, fixer.positions, f)
    return pdb_out


# ---------- step 4: receptor PDBQT (Meeko) ----------
def receptor_to_pdbqt(clean_pdb, out_pdbqt):
    """Prefer Meeko's mk_prepare_receptor CLI (permissive); fall back to prepare_receptor."""
    if shutil.which("mk_prepare_receptor.py"):
        stem = out_pdbqt[:-6] if out_pdbqt.endswith(".pdbqt") else out_pdbqt
        subprocess.run(["mk_prepare_receptor.py", "--read_pdb", clean_pdb, "-o", stem, "-p"],
                       check=True, capture_output=True, text=True)
        cand = stem + ".pdbqt"
        if os.path.exists(cand):
            if cand != out_pdbqt:
                shutil.move(cand, out_pdbqt)
            return out_pdbqt
    if shutil.which("prepare_receptor"):
        subprocess.run(["prepare_receptor", "-r", clean_pdb, "-o", out_pdbqt],
                       check=True, capture_output=True, text=True)
        return out_pdbqt
    raise RuntimeError("no receptor-prep tool found. `pip install meeko` (mk_prepare_receptor) "
                       "or install ADFR/MGLTools prepare_receptor.")


# ---------- orchestration ----------
def prepare_receptor(pdb_path, target_id, name=None, ref_resname=None, chain=None,
                     out_dir="docking_targets", padding=8.0):
    tdir = os.path.join(out_dir, target_id)
    os.makedirs(tdir, exist_ok=True)

    ref_coords, ref_name, n_ref = extract_reference_ligand(pdb_path, ref_resname, chain)
    center, box_size = grid_box_from_ligand(ref_coords, padding=padding)

    prot = strip_to_protein(pdb_path, os.path.join(tdir, "protein_raw.pdb"), chain=chain)
    clean = repair_receptor(prot, os.path.join(tdir, "receptor_clean.pdb"))
    rec_pdbqt = receptor_to_pdbqt(clean, os.path.join(tdir, "receptor.pdbqt"))

    profile = {
        "target_id": target_id, "name": name or target_id,
        "pdb_source": os.path.basename(pdb_path), "reference_ligand_resname": ref_name,
        # store PORTABLE basenames, not absolute paths — resolved at load time
        # relative to DOCKING_TARGETS_DIR/<target_id>/ (see profile.load_profile),
        # so the registry keeps working after the project moves or is packaged.
        "receptor_pdbqt": os.path.basename(rec_pdbqt),
        "receptor_pdb": os.path.basename(clean),
        "center": center, "box_size": box_size,
        "site_source": "co-crystal_ligand" if ref_resname or ref_name else "auto",
        "validated": False,           # flip to True only after redock RMSD < 2 A
    }
    # merge into registry
    reg = {}
    if os.path.exists(REGISTRY):
        data = json.load(open(REGISTRY))
        reg = {t["target_id"]: t for t in data.get("targets", [])}
    reg[target_id] = profile
    json.dump({"targets": list(reg.values())}, open(REGISTRY, "w"), indent=2)
    return profile