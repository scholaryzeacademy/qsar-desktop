"""Detect which docking tools/packages are present. [TESTED]"""
import shutil, importlib

# external binaries
BINARIES = {
    "vina": "AutoDock Vina (Apache-2.0) — docking engine",
    "gnina": "GNINA (Apache-2.0) — CNN rescoring / second opinion (optional)",
    "fpocket": "fpocket — pocket detection fallback (optional)",
}
# python packages
PACKAGES = {
    "rdkit": "chemistry toolkit",
    "meeko": "permissive ligand/receptor PDBQT prep",
    "posebusters": "physical-validity gate",
    "pdbfixer": "receptor repair (missing atoms/H)",
    "matplotlib": "2D interaction diagrams",
}


def _has_pkg(name):
    try:
        importlib.import_module(name); return True
    except Exception:
        return False


def status():
    bins = {b: (shutil.which(b) is not None) for b in BINARIES}
    pkgs = {p: _has_pkg(p) for p in PACKAGES}
    can_prep_ligand = pkgs["rdkit"] and pkgs["meeko"]
    can_validate = pkgs["posebusters"] and pkgs["rdkit"]
    can_dock = bins["vina"]                          # Vina is the engine
    ready = can_prep_ligand and can_dock
    missing = ([f"binary:vina"] if not bins["vina"] else []) + \
              [f"pkg:{p}" for p in ("rdkit", "meeko", "posebusters") if not pkgs[p]]
    return {
        "ready": bool(ready),
        "can_prep_ligand": can_prep_ligand,
        "can_validate": can_validate,
        "can_dock": can_dock,
        "has_gnina": bins["gnina"],                  # optional second opinion
        "binaries": bins, "packages": pkgs,
        "binary_desc": BINARIES, "package_desc": PACKAGES,
        "missing_for_docking": missing,
        "note": ("Docking needs a ligand-prep stack (rdkit+meeko), a validity gate "
                 "(posebusters), and the Vina engine. GNINA is an optional CNN "
                 "second-opinion rescorer. Install the missing items to enable docking."),
    }