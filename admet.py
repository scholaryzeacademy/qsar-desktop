"""
============================================================
  ADMET CLIENT  (admet.py)  —  runs inside the main web app
============================================================
  LAYER 1 - DETERMINISTIC  [local, RDKit, always on]:
      physicochemical, drug-likeness FLAGS (never filters), alerts.

  LAYER 2 - LEARNED  [ADMET-AI, via the separate WORKER service]:
      The heavy ADMET-AI stack runs in admet_service.py (its own process,
      port 8100 by default) so it cannot freeze the main app. This module
      just calls it over HTTP and maps its columns into A/D/M/E/T groups
      (see admet_endpoints.py). If the worker is down, the deterministic
      layer is returned with a clear notice.

  Configure the worker URL with env ADMET_SERVICE_URL (default 127.0.0.1:8100).
============================================================
"""
import os
import time
import warnings
warnings.filterwarnings("ignore")

from rdkit import Chem
from rdkit.Chem import QED, Descriptors, Crippen, rdMolDescriptors
from rdkit.Chem.FilterCatalog import FilterCatalog, FilterCatalogParams

import admet_endpoints as EP

try:
    import httpx
except Exception:
    httpx = None

try:
    from pipeline import standardise_smiles
except Exception:
    def standardise_smiles(s):
        m = Chem.MolFromSmiles(s); return Chem.MolToSmiles(m) if m else None

WORKER_URL = os.environ.get("ADMET_SERVICE_URL", "http://127.0.0.1:8100").rstrip("/")

# ---------- structural-alert catalogs ----------
def _one(cat):
    p = FilterCatalogParams(); p.AddCatalog(cat); return FilterCatalog(p)
_CATALOGS = {"PAINS": _one(FilterCatalogParams.FilterCatalogs.PAINS),
             "BRENK": _one(FilterCatalogParams.FilterCatalogs.BRENK),
             "NIH":   _one(FilterCatalogParams.FilterCatalogs.NIH)}

# ---------- deterministic layer ----------
def _physchem(m):
    return {"mw": round(Descriptors.MolWt(m), 1), "logp": round(Crippen.MolLogP(m), 2),
            "tpsa": round(rdMolDescriptors.CalcTPSA(m), 1), "hbd": rdMolDescriptors.CalcNumHBD(m),
            "hba": rdMolDescriptors.CalcNumHBA(m), "rotatable_bonds": rdMolDescriptors.CalcNumRotatableBonds(m),
            "aromatic_rings": rdMolDescriptors.CalcNumAromaticRings(m),
            "fraction_sp3": round(rdMolDescriptors.CalcFractionCSP3(m), 3),
            "heavy_atoms": m.GetNumHeavyAtoms(), "qed": round(QED.qed(m), 3)}

def _rules(pc):
    lip = sum([pc["mw"] > 500, pc["logp"] > 5, pc["hbd"] > 5, pc["hba"] > 10])
    return {"lipinski_violations": int(lip), "lipinski_pass": lip <= 1,
            "veber_pass": bool(pc["rotatable_bonds"] <= 10 and pc["tpsa"] <= 140),
            "egan_pass": bool(pc["tpsa"] <= 131.6 and -1 <= pc["logp"] <= 5.88),
            "ghose_pass": bool(160 <= pc["mw"] <= 480 and -0.4 <= pc["logp"] <= 5.6 and 20 <= pc["heavy_atoms"] <= 70),
            "_note": "Informational only; natural products commonly violate these while remaining bioactive. Never used to filter or penalise."}

def _alerts(m):
    return [{"catalog": n, "description": e.GetDescription()}
            for n, cat in _CATALOGS.items() for e in cat.GetMatches(m)]

def _cautions(pc, alerts):
    c = []
    if any(a["catalog"] == "PAINS" for a in alerts):
        c.append("Matches a PAINS substructure — may assay-interfere; verify experimentally.")
    if pc["logp"] > 6.5:
        c.append("Very high lipophilicity (LogP > 6.5) — solubility/permeability risk.")
    if pc["mw"] > 800:
        c.append("Large molecule (MW > 800) — oral absorption less likely (common for glycosides/natural products).")
    return c

def deterministic_profile(smiles):
    cs = standardise_smiles(smiles)
    m = Chem.MolFromSmiles(cs) if cs else None
    if m is None or m.GetNumHeavyAtoms() == 0:
        return {"input_smiles": smiles, "parsed_ok": False}
    pc = _physchem(m); alerts = _alerts(m)
    return {"input_smiles": smiles, "standardised_smiles": cs, "parsed_ok": True,
            "physicochemical": pc, "drug_likeness_flags": _rules(pc),
            "structural_alerts": alerts, "n_alerts": len(alerts), "cautions": _cautions(pc, alerts)}

def deterministic_profiles(smiles_list):
    return [deterministic_profile(s) for s in smiles_list]

# ---------- learned grouping ----------
def _tone(task, polarity, value):
    if task != "class" or polarity == "neutral" or value is None:
        return "neutral"
    if polarity == "risk":
        return "bad" if value >= EP.RISK_HIGH else ("warn" if value >= EP.RISK_MED else "good")
    return "good" if value >= EP.RISK_HIGH else ("warn" if value >= EP.RISK_MED else "bad")

def grouped_learned(row):
    groups = {g: [] for g in EP.GROUP_ORDER}
    flags = []
    for name, (grp, label, task, unit, pol) in EP.ENDPOINTS.items():
        if name not in row:
            continue
        val = row.get(name)
        val = None if val is None else round(float(val), 3)
        pct = row.get(f"{name}_drugbank_approved_percentile")
        tone = _tone(task, pol, val)
        disp = (f"{round(val*100)}%" if task == "class" and val is not None
                else (f"{val} {unit}" if val is not None else "—"))
        groups.setdefault(grp, []).append({"name": name, "label": label, "task": task, "unit": unit,
                                            "value": val, "display": disp, "tone": tone,
                                            "percentile": None if pct is None else round(float(pct), 1)})
        if tone == "bad":
            flags.append(f"{label} ({disp})")
    return {"available": True, "source": "ADMET-AI",
            "groups": {g: v for g, v in groups.items() if v}, "flags": flags}

def attach_learned(det_profiles, predictions):
    """predictions: {standardised_smiles: {col: val}}. Merge grouped learned into det profiles."""
    for p in det_profiles:
        if not p.get("parsed_ok"):
            p["learned"] = {"available": False, "note": "unparsed"}
            continue
        row = predictions.get(p["standardised_smiles"])
        p["learned"] = grouped_learned(row) if row else {"available": False, "note": "no prediction returned"}
    return det_profiles

# ---------- worker client ----------
_health_cache = {"t": 0, "val": None, "ttl": 15}

def learned_status():
    now = time.time()
    if _health_cache["val"] is not None and now - _health_cache["t"] < _health_cache["ttl"]:
        return _health_cache["val"]
    val = {"available": False, "source": "ADMET-AI",
           "note": ("Learned ADMET endpoints are unavailable — the ADMET-AI worker service is not "
                    "reachable. Start it with `uvicorn admet_service:app --port 8100` (needs "
                    "`pip install admet-ai`). The deterministic drug-likeness layer is always available.")}
    if httpx is not None:
        try:
            r = httpx.get(f"{WORKER_URL}/health", timeout=2.0, trust_env=False)
            if r.status_code == 200 and r.json().get("available"):
                val = {"available": True, "source": "ADMET-AI"}
        except Exception:
            pass
    # Cache a positive result for 15s, but a negative for only 3s so the app
    # re-probes quickly and self-heals once the worker comes up (no restart needed).
    _health_cache.update(t=now, val=val, ttl=(15 if val["available"] else 3))
    return val

def worker_profile(std_smiles, timeout=180.0):
    """Synchronous learned prediction for a small list. Returns predictions dict or None."""
    if httpx is None:
        return None
    try:
        r = httpx.post(f"{WORKER_URL}/profile", json={"smiles": std_smiles}, timeout=timeout, trust_env=False)
        r.raise_for_status()
        d = r.json()
        return d.get("predictions") if d.get("available") else None
    except Exception:
        return None

def worker_submit(std_smiles, timeout=15.0):
    if httpx is None:
        return None
    try:
        r = httpx.post(f"{WORKER_URL}/jobs", json={"smiles": std_smiles}, timeout=timeout, trust_env=False)
        r.raise_for_status()
        return r.json().get("job_id")
    except Exception:
        return None

def worker_poll(job_id, timeout=15.0):
    if httpx is None:
        return None
    try:
        r = httpx.get(f"{WORKER_URL}/jobs/{job_id}", timeout=timeout, trust_env=False)
        r.raise_for_status()
        return r.json()
    except Exception:
        return None

# ---------- convenience (synchronous full profile; used by compare + small ADMET) ----------
def admet_profiles(smiles_list):
    det = deterministic_profiles(smiles_list)
    status = learned_status()
    std = [p["standardised_smiles"] for p in det if p.get("parsed_ok")]
    if status["available"] and std:
        preds = worker_profile(std)
        if preds is not None:
            return attach_learned(det, preds)
    for p in det:
        p["learned"] = {"available": False, "note": status.get("note")}
    return det

def admet_profile(smiles):
    return admet_profiles([smiles])[0]