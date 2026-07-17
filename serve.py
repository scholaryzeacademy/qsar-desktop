"""
============================================================
  SERVE CORE (serve.py)  —  serving-app side only
============================================================
  This directory is the SERVING app. The model FACTORY lives elsewhere.
  You copy in:  registry.json  (from the factory)  +  the .pkl model files.

  Model paths are resolved robustly: the asset_path in registry.json is
  tried as-is, then by basename under ./models/, then by a recursive search
  — so it works whether you copy the whole models/ tree or just loose .pkl
  files into models/.
============================================================
"""
import os
import json
import glob
import pickle
import functools
import warnings
warnings.filterwarnings("ignore")

import pipeline as P

REGISTRY = os.environ.get("PHYTO_REGISTRY", "registry.json")
MODELS_DIR = os.environ.get("PHYTO_MODELS", "models")


def load_registry():
    if not os.path.exists(REGISTRY):
        return {}
    with open(REGISTRY) as f:
        data = json.load(f)
    models = data.get("models", data if isinstance(data, list) else [])
    return {r["target_id"]: r for r in models}


def resolve_asset(rec):
    """Find the .pkl for a registry record, tolerant of how it was copied in."""
    tid = rec.get("target_id")
    ap = rec.get("asset_path")
    base = os.path.basename(ap) if ap else (f"{tid}_qsar_model.pkl" if tid else None)
    candidates = []
    if ap:
        candidates.append(ap)
    if base:
        candidates += [os.path.join(MODELS_DIR, tid or "", base),
                       os.path.join(MODELS_DIR, base)]
    for c in candidates:
        if c and os.path.exists(c):
            return c
    if base and os.path.isdir(MODELS_DIR):
        hits = glob.glob(os.path.join(MODELS_DIR, "**", base), recursive=True)
        if hits:
            return hits[0]
    return None


def asset_available(rec):
    return resolve_asset(rec) is not None


@functools.lru_cache(maxsize=64)
def load_model(target_id):
    reg = load_registry()
    if target_id not in reg:
        raise KeyError(f"unknown target '{target_id}'")
    rec = reg[target_id]
    if rec.get("status") == "failed":
        raise RuntimeError(f"target '{target_id}' failed to build: {rec.get('error')}")
    path = resolve_asset(rec)
    if not path:
        raise FileNotFoundError(f"model file for '{target_id}' not found — copy its .pkl into {MODELS_DIR}/")
    with open(path, "rb") as f:
        return pickle.load(f), rec


def rank(target_id, smiles_list, model_name=None, batch=2000, progress=False):
    asset, rec = load_model(target_id)
    model_name = model_name or asset["best_name"]
    if model_name not in P.list_models(asset):
        raise ValueError(f"unknown model '{model_name}'. Options: {P.list_models(asset)}")
    in_dom, out_dom, sort_col = P.screen(asset, smiles_list, model_name=model_name,
                                         batch=batch, progress=progress)
    return in_dom, out_dom, sort_col, rec, model_name