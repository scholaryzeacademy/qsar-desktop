"""Docking target profiles (per-target receptor + box + reference).  [TESTED: load/save/box]"""
import os, json
import numpy as np

REGISTRY = os.environ.get("DOCKING_REGISTRY", "docking_registry.json")


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


def load_profile(target_id):
    reg = load_registry()
    if target_id not in reg:
        raise KeyError(f"no docking profile for '{target_id}'")
    return reg[target_id]


def save_registry(profiles):
    with open(REGISTRY, "w") as f:
        json.dump({"targets": list(profiles.values())}, f, indent=2)