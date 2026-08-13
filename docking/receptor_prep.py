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
def _minimize_added_atoms(fixer, max_iterations=300):
    """PDBFixer's addMissingAtoms()/addMissingHydrogens() place new atoms
       from geometric templates with no clash-checking against the rest of
       the residue — for a residue whose crystal structure was missing a
       sidechain (or part of one), this can drop the rebuilt atoms almost on
       top of one another. Observed on ADRB1/7BU6: GLN284 and ARG366 each got
       a sidechain CG landing 1.56 A from their own NE2/CZ — a 1-3
       (two-bonds-apart) distance that should be ~2.3-2.4 A. Meeko's
       receptor-to-mol step infers bonds from interatomic distance alone
       (see _drop_oxt below for the other flavor of this bug), so that clash
       reads as a real bond and blows the atom's valence, crashing
       mk_prepare_receptor.py with an RDKit AtomValenceException.

       A short vacuum energy minimization relaxes exactly these local
       clashes — real bonded geometry already sits in a deep energy well, so
       nothing conformationally meaningful moves; confirmed on the case
       above (energy dropped from +4e5 to -5e4 kJ/mol, CG-NE2 distance
       corrected to 2.45 A, ~2s on the CPU platform for a ~7200-atom
       receptor) before the structure ever reaches Meeko."""
    from openmm import app, unit, LocalEnergyMinimizer, VerletIntegrator, Context, Platform
    forcefield = app.ForceField("amber14-all.xml")
    system = forcefield.createSystem(fixer.topology, nonbondedMethod=app.NoCutoff,
                                     constraints=None, rigidWater=False)
    integrator = VerletIntegrator(1.0 * unit.femtoseconds)
    try:
        platform = Platform.getPlatformByName("CPU")
    except Exception:
        platform = Platform.getPlatformByName("Reference")
    context = Context(system, integrator, platform)
    context.setPositions(fixer.positions)
    LocalEnergyMinimizer.minimize(context, maxIterations=max_iterations)
    fixer.positions = context.getState(getPositions=True).getPositions()


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
    try:
        _minimize_added_atoms(fixer)
    except Exception:
        pass   # best-effort clash relief — a forcefield-template mismatch here must not block receptor prep
    with open(pdb_out, "w") as f:
        PDBFile.writeFile(fixer.topology, fixer.positions, f)
    _drop_oxt(pdb_out)
    return pdb_out


def _drop_oxt(pdb_path):
    """Remove C-terminal OXT atoms in place. PDBFixer completes every chain
       terminus with one (standard chemistry), but Meeko's PDB->mol step
       perceives bond orders from interatomic distance alone: the terminal
       carbon's two near-equidistant C-O contacts (O and OXT) both get read
       as double bonds, pushing its valence to 5 and crashing receptor prep
       on EVERY chain terminus. Vina scores a rigid receptor purely from atom
       positions/types (no formal bond orders), so dropping this one terminal
       oxygen costs nothing chemically relevant to docking — confirmed fix
       against CHEMBL1862_ABL1/1IEP (chains A and B both hit this)."""
    with open(pdb_path) as f:
        lines = f.readlines()
    kept = [ln for ln in lines
            if not (ln.startswith(("ATOM", "HETATM")) and ln[12:16].strip() == "OXT")]
    with open(pdb_path, "w") as f:
        f.writelines(kept)


# ---------- step 4: receptor PDBQT (Meeko) ----------
def receptor_to_pdbqt(clean_pdb, out_pdbqt):
    """Prefer Meeko's mk_prepare_receptor CLI (permissive); fall back to prepare_receptor."""
    if shutil.which("mk_prepare_receptor.py"):
        stem = out_pdbqt[:-6] if out_pdbqt.endswith(".pdbqt") else out_pdbqt
        try:
            subprocess.run(["mk_prepare_receptor.py", "--read_pdb", clean_pdb, "-o", stem, "-p"],
                           check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as e:
            # surface meeko's actual error — a bare CalledProcessError hides the
            # one line (usually an RDKit sanitization failure on a specific
            # residue) that says WHY prep failed, forcing anyone debugging this
            # to blindly re-run the subprocess by hand to find out.
            raise RuntimeError(f"mk_prepare_receptor.py failed on {clean_pdb}:\n{e.stderr}") from e
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


# ---------- binding site (pocket residues, for showing WHY the box sits
# where it does — not just an opaque center/size) ----------
def locate_ligand_near(pdb_path, resname, near_point, chain=None):
    """Among every HETATM group named `resname` in pdb_path (any chain unless
       `chain` is given), return the heavy-atom coords of whichever copy's
       centroid is closest to `near_point`. Chain isn't persisted in
       docking_registry.json, but the box center a profile actually produced
       IS — distance-matching against that recovers the exact ligand copy a
       profile was built from even for structures depositing 2+ copies in
       the asymmetric unit (e.g. 1IEP/ABL1, see detect_chain.py)."""
    from Bio.PDB import PDBParser
    s = PDBParser(QUIET=True).get_structure("x", pdb_path)
    near = np.asarray(near_point, float)
    best = None
    for model in s:
        for ch in model:
            if chain and ch.id != chain:
                continue
            for res in ch:
                if res.resname.strip() != resname:
                    continue
                coords = np.array([a.coord for a in res.get_atoms()], float)
                d = float(np.linalg.norm(coords.mean(axis=0) - near))
                if best is None or d < best[0]:
                    best = (d, coords)
        break
    if best is None:
        raise ValueError(f"ligand '{resname}' not found in {pdb_path}")
    return best[1]


def pocket_residues(clean_pdb_path, ref_coords, cutoff=5.0):
    """Receptor residues with any atom within `cutoff` A of any reference-
       ligand atom — the binding site shown to users before docking runs,
       instead of leaving 'why does the box sit here' implicit."""
    from Bio.PDB import PDBParser, NeighborSearch
    s = PDBParser(QUIET=True).get_structure("x", clean_pdb_path)
    ns = NeighborSearch(list(s.get_atoms()))
    seen = {}
    for pt in ref_coords:
        for atom in ns.search(pt, cutoff):
            res = atom.get_parent()
            key = (res.get_parent().id, res.id[1], res.resname.strip())
            seen[key] = True
    out = [{"chain": k[0], "resnum": k[1], "resname": k[2]} for k in seen]
    out.sort(key=lambda r: (r["chain"], r["resnum"]))
    return out


def box_from_residues(clean_pdb_path, residues, padding=8.0, min_size=20.0):
    """center/box_size (grid_box_from_ligand's contract) from a user-picked
       residue subset — Advanced Settings' 'define a custom binding site
       from residues' path, an alternative to typing raw coordinates."""
    from Bio.PDB import PDBParser
    s = PDBParser(QUIET=True).get_structure("x", clean_pdb_path)
    want = {(r["chain"], int(r["resnum"])) for r in residues}
    coords = []
    for model in s:
        for ch in model:
            for res in ch:
                if (ch.id, res.id[1]) in want:
                    coords.extend(a.coord for a in res.get_atoms())
        break
    if not coords:
        raise ValueError("none of the given residues were found in this receptor")
    return grid_box_from_ligand(coords, padding=padding, min_size=min_size)


def box_from_receptor(clean_pdb_path, padding=4.0, min_size=20.0):
    """Whole-protein bounding box — the 'blind docking' path (no pocket
       assumption at all, as opposed to the ligand-centered or residue-
       selected site-specific boxes above). Smaller padding than the
       site-specific default (4 A vs 8 A): the box already spans the whole
       receptor, so there's no need for the extra margin a small, focused
       pocket box wants. Vina still has to search a MUCH larger volume than
       a site-specific box, so this is inherently slower and less reliable
       per-site than a validated pocket — callers should surface that as a
       caveat, not silently treat blind results as equally trustworthy."""
    from Bio.PDB import PDBParser
    s = PDBParser(QUIET=True).get_structure("x", clean_pdb_path)
    coords = [a.coord for a in s.get_atoms()]
    if not coords:
        raise ValueError(f"no atoms found in {clean_pdb_path}")
    return grid_box_from_ligand(coords, padding=padding, min_size=min_size)


# ---------- orchestration ----------
def build_receptor(pdb_path, target_id, name=None, ref_resname=None, chain=None,
                   out_dir="docking_targets", padding=8.0):
    """Runs the full strip -> repair -> PDBQT pipeline and returns a profile
       dict with ABSOLUTE file paths — no docking_registry.json I/O. Used by
       both prepare_receptor() (build-time, persists into the shared
       registry below) and app.py's on-demand 'Advanced Settings' manual
       structure override (deliberately never persisted — an expert's
       per-request pick shouldn't silently overwrite the vetted default, and
       staying out of the shared registry file avoids racing a concurrent
       batch_validate.py run that owns writes to it)."""
    tdir = os.path.join(out_dir, target_id)
    os.makedirs(tdir, exist_ok=True)

    ref_coords, ref_name, n_ref = extract_reference_ligand(pdb_path, ref_resname, chain)
    center, box_size = grid_box_from_ligand(ref_coords, padding=padding)

    prot = strip_to_protein(pdb_path, os.path.join(tdir, "protein_raw.pdb"), chain=chain)
    clean = repair_receptor(prot, os.path.join(tdir, "receptor_clean.pdb"))
    rec_pdbqt = receptor_to_pdbqt(clean, os.path.join(tdir, "receptor.pdbqt"))

    try:
        binding_site_residues = pocket_residues(clean, ref_coords, cutoff=5.0)
    except Exception:
        binding_site_residues = []   # non-fatal — box/docking still work without this display data
    try:
        blind_center, blind_box_size = box_from_receptor(clean)
    except Exception:
        blind_center, blind_box_size = None, None   # non-fatal — blind mode just won't be offered for this structure

    return {
        "target_id": target_id, "name": name or target_id,
        "pdb_source": os.path.basename(pdb_path), "reference_ligand_resname": ref_name,
        "chain": chain,                # persisted so a later revert/repair (see batch_validate.py's
                                        # _accept_or_revert) can rebuild an IDENTICAL receptor from
                                        # scratch — without this, a revert only restored the registry's
                                        # center/box_size/pdb_source, not which chain was stripped to,
                                        # so a rebuild from raw pdb_source alone could silently include
                                        # extra chains never present in the originally-validated receptor.
        "receptor_pdbqt": os.path.abspath(rec_pdbqt),
        "receptor_pdb": os.path.abspath(clean),
        "center": center, "box_size": box_size,
        "binding_site_residues": binding_site_residues,
        "blind_center": blind_center, "blind_box_size": blind_box_size,
        "site_source": "co-crystal_ligand" if ref_resname or ref_name else "auto",
        "validated": False,           # flip to True only after redock RMSD < 2 A
    }


def prepare_receptor(pdb_path, target_id, name=None, ref_resname=None, chain=None,
                     out_dir="docking_targets", padding=8.0):
    """Build-time onboarding: build_receptor() + persist into the shared
       docking_registry.json with portable (basename) paths."""
    profile = build_receptor(pdb_path, target_id, name=name, ref_resname=ref_resname,
                             chain=chain, out_dir=out_dir, padding=padding)
    # store PORTABLE basenames, not absolute paths — resolved at load time
    # relative to DOCKING_TARGETS_DIR/<target_id>/ (see profile.load_profile),
    # so the registry keeps working after the project moves or is packaged.
    profile = dict(profile, receptor_pdbqt=os.path.basename(profile["receptor_pdbqt"]),
                   receptor_pdb=os.path.basename(profile["receptor_pdb"]))
    reg = {}
    if os.path.exists(REGISTRY):
        data = json.load(open(REGISTRY))
        reg = {t["target_id"]: t for t in data.get("targets", [])}
    reg[target_id] = profile
    json.dump({"targets": list(reg.values())}, open(REGISTRY, "w"), indent=2)
    return profile