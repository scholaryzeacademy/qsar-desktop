"""Docking target profiles (per-target receptor + box + reference).  [TESTED: load/save/box]"""
import os, json
import numpy as np

REGISTRY = os.environ.get("DOCKING_REGISTRY", "docking_registry.json")
DOCKING_TARGETS_DIR = os.environ.get("DOCKING_TARGETS_DIR", "docking_targets")


def grid_box_from_ligand(coords, padding=8.0, min_size=20.0):
    """Center + size (A) of the search box from reference-ligand heavy-atom coords."""
    c = np.asarray(coords, float)
    center = c.mean(axis=0)
    size = (c.max(axis=0) - c.min(axis=0)) + 2 * padding
    size = np.maximum(size, min_size)
    return [round(float(x), 3) for x in center], [round(float(x), 3) for x in size]


def load_registry():
    if not os.path.exists(REGISTRY):
        return {}
    with open(REGISTRY) as f:
        data = json.load(f)
    items = data.get("targets", data if isinstance(data, list) else [])
    return {t["target_id"]: t for t in items}


def _resolve_receptor_path(target_id, filename_or_path):
    """Resolve a receptor file portably. Registries may store either just a
       basename (portable, preferred going forward) or a legacy absolute
       path from wherever the profile was first built — that absolute path
       breaks the moment the project folder moves or is packaged onto a
       different machine (e.g. a Windows .exe), so it's only trusted if it
       still exists; otherwise we fall back to DOCKING_TARGETS_DIR/<target_id>/<basename>."""
    if filename_or_path and os.path.isabs(filename_or_path) and os.path.exists(filename_or_path):
        return filename_or_path
    base = os.path.basename(filename_or_path) if filename_or_path else None
    if base:
        cand = os.path.join(DOCKING_TARGETS_DIR, target_id, base)
        if os.path.exists(cand):
            return cand
    return filename_or_path  # let the caller's own existence checks fail loudly and clearly


def load_profile(target_id):
    reg = load_registry()
    if target_id not in reg:
        raise KeyError(f"no docking profile for '{target_id}'")
    p = dict(reg[target_id])
    p["receptor_pdbqt"] = _resolve_receptor_path(target_id, p.get("receptor_pdbqt"))
    p["receptor_pdb"] = _resolve_receptor_path(target_id, p.get("receptor_pdb"))
    return p


def save_registry(profiles):
    with open(REGISTRY, "w") as f:
        json.dump({"targets": list(profiles.values())}, f, indent=2)