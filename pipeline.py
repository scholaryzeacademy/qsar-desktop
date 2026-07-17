"""
============================================================
  QSAR FACTORY ENGINE  (pipeline.py)
============================================================
  The FROZEN engine. You do not edit this per target — you edit
  targets.yaml. Every protein target (single-protein IC50 -> pIC50)
  is built by this identical, validated code path:

    curate()  -> clean, target-locked dataset from a raw ChEMBL CSV
    train()   -> leak-free model + AD + conformal, stamped asset
    screen()  -> rank SMILES by the conformal lower bound (serve side)
    gate()    -> decide if a model is good enough to publish "live"

  Correctness carried over from the single-target scripts:
    units filter, pChEMBL audit, replicate-RANGE filter, target lock,
    train/val/calib/test split, selection on val, single test report,
    Tanimoto AD, normalized split-conformal intervals + lower bound.
============================================================
"""

import os
import json
import datetime
import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd

from rdkit import Chem, DataStructs, RDLogger
from rdkit.Chem import Descriptors, MACCSkeys, rdFingerprintGenerator
from rdkit.Chem.Scaffolds import MurckoScaffold
from rdkit.Chem.MolStandardize import rdMolStandardize

from sklearn.feature_selection import VarianceThreshold
from sklearn.preprocessing import StandardScaler
from sklearn.ensemble import (RandomForestRegressor, ExtraTreesRegressor,
                              GradientBoostingRegressor)
from sklearn.linear_model import RidgeCV
from sklearn.metrics import r2_score, mean_squared_error, mean_absolute_error
from scipy.stats import spearmanr

RDLogger.DisableLog("rdApp.*")

# ============================================================
#   GLOBAL DEFAULTS  (overridable per target in targets.yaml)
# ============================================================
DEFAULTS = {
    # --- curation ---
    "pic50_min": 3.0, "pic50_max": 12.0,
    "replicate_range_max": 1.0,
    "filter_organism": True, "organism": "Homo sapiens",
    "filter_assay_format": True, "single_protein_bao": "BAO_0000357",
    "pchembl_tol": 0.10,
    # --- modeling ---
    "random_state": 42,
    "rich_features": True,
    "corr_threshold": 0.90, "max_corr_feats": 8000,
    "ad_k": 5, "ad_z": 3.0,
    "n_cv_repeats": 5,
    "conformal_confidence": 0.90, "sigma_floor": 0.10, "sigma_ad_lambda": 1.5,
    # --- quality gate (publish "live" only if ALL pass) ---
    "gate_min_compounds": 300,
    "gate_min_spearman": 0.40,
    "gate_conformal_tolerance": 0.07,     # |coverage - confidence| must be <= this
    "gate_require_ad_discriminates": True,
}

# ChEMBL raw-export column names (fixed; not per target)
C = dict(target="Target ChEMBL ID", mol="Molecule ChEMBL ID", smiles="Smiles",
         typ="Standard Type", rel="Standard Relation", val="Standard Value",
         units="Standard Units", valid="Data Validity Comment",
         pchembl="pChEMBL Value", bao="BAO Format ID", org="Assay Organism",
         assay="Assay ChEMBL ID")

BIT_PREFIXES = ("MACCS_", "ECFP4_", "ECFP6_", "AP_")

def cfg_for(target, defaults=DEFAULTS):
    """Merge global defaults with a per-target dict (target overrides win)."""
    c = dict(defaults); c.update({k: v for k, v in target.items() if v is not None})
    return c

# ============================================================
#   FEATURISATION (shared everywhere)
# ============================================================
_lfc  = rdMolStandardize.LargestFragmentChooser()
_unch = rdMolStandardize.Uncharger()
_m2   = rdFingerprintGenerator.GetMorganGenerator(radius=2, fpSize=2048)
_m3   = rdFingerprintGenerator.GetMorganGenerator(radius=3, fpSize=2048)
_ap   = rdFingerprintGenerator.GetAtomPairGenerator(fpSize=2048)
_DESCS = list(Descriptors.descList)

def standardise_smiles(smi):
    try:
        m = Chem.MolFromSmiles(smi)
        if m is None:
            return None
        m = rdMolStandardize.Cleanup(m); m = _lfc.choose(m); m = _unch.uncharge(m)
        return Chem.MolToSmiles(m)
    except Exception:
        return None

def featurise(smi, rich=True):
    m = Chem.MolFromSmiles(smi)
    if m is None or m.GetNumHeavyAtoms() == 0:   # reject empty / salt-only / zero-atom mols
        return None, None
    # per-descriptor guard: one bad descriptor must not kill the molecule (or the batch)
    d = {}
    for name, func in _DESCS:
        try:
            v = func(m)
            d[name] = v if v is not None and np.isfinite(v) else 0.0
        except Exception:
            d[name] = 0.0
    try:
        for i, b in enumerate(MACCSkeys.GenMACCSKeys(m)):
            d[f"MACCS_{i}"] = b
        e = _m2.GetFingerprint(m)
        for i, b in enumerate(e):
            d[f"ECFP4_{i}"] = b
        if rich:
            for i, b in enumerate(_m3.GetFingerprint(m)):
                d[f"ECFP6_{i}"] = b
            for i, b in enumerate(_ap.GetFingerprint(m)):
                d[f"AP_{i}"] = b
    except Exception:
        return None, None
    return d, e

def ecfp4_bv(smi):
    m = Chem.MolFromSmiles(smi)
    return _m2.GetFingerprint(m) if (m is not None and m.GetNumHeavyAtoms() > 0) else None

def knn_tanimoto_distance(bv, ref, k, drop_self=False):
    sims = DataStructs.BulkTanimotoSimilarity(bv, ref)
    sims.sort(reverse=True)
    if drop_self:
        sims = sims[1:]
    top = sims[:k] if len(sims) >= k else sims
    return 1.0 - (sum(top) / len(top))

# ============================================================
#   CURATION
# ============================================================
def _norm_rel(s):
    return s.astype(str).str.replace("'", "", regex=False).str.replace('"', "", regex=False).str.strip()

def curate(cfg):
    """Raw ChEMBL CSV -> (clean_df[ChEMBL_ID,SMILES,pIC50], meta). Target-locked."""
    raw = cfg["raw_csv"]
    if not os.path.exists(raw):
        raise FileNotFoundError(f"raw_csv not found: {raw}")
    df = pd.read_csv(raw, sep=";", low_memory=False)
    log = {"loaded": len(df)}

    if C["target"] not in df.columns:
        raise ValueError(f"'{C['target']}' column missing — cannot verify target.")
    present = df[C["target"]].dropna().unique().tolist()
    if cfg["chembl_id"] not in present:
        raise ValueError(f"TARGET MISMATCH: expected {cfg['chembl_id']}, file has {present}")
    df = df[df[C["target"]] == cfg["chembl_id"]].copy(); log["target_locked"] = len(df)

    df = df[df[C["typ"]] == "IC50"].copy(); log["ic50"] = len(df)
    df = df[_norm_rel(df[C["rel"]]) == "="].copy(); log["exact_rel"] = len(df)
    df = df[df[C["units"]] == "nM"].copy(); log["units_nM"] = len(df)
    if C["valid"] in df.columns:
        df = df[df[C["valid"]].isna() | (df[C["valid"]].astype(str).str.strip() == "")].copy()
    log["valid"] = len(df)
    if cfg["filter_organism"] and C["org"] in df.columns:
        df = df[df[C["org"]] == cfg["organism"]].copy()
    log["organism"] = len(df)
    if cfg["filter_assay_format"] and C["bao"] in df.columns:
        df = df[df[C["bao"]] == cfg["single_protein_bao"]].copy()
    log["assay_format"] = len(df)

    keep = [c for c in [C["mol"], C["smiles"], C["val"], C["pchembl"], C["assay"]] if c in df.columns]
    df = df[keep].rename(columns={C["mol"]: "ChEMBL_ID", C["smiles"]: "SMILES",
                                  C["val"]: "IC50_nM", C["pchembl"]: "pChEMBL"})
    df["IC50_nM"] = pd.to_numeric(df["IC50_nM"], errors="coerce")
    df["pChEMBL"] = pd.to_numeric(df.get("pChEMBL", np.nan), errors="coerce")
    df = df.dropna(subset=["SMILES", "IC50_nM"])
    df = df[(df["SMILES"].astype(str).str.strip() != "") & (df["IC50_nM"] > 0)]
    log["non_null"] = len(df)

    dsub = [c for c in ["ChEMBL_ID", "SMILES", "IC50_nM",
                        ("Assay ChEMBL ID" if "Assay ChEMBL ID" in df.columns else None)] if c]
    df = df.drop_duplicates(subset=dsub).copy(); log["dedup"] = len(df)

    df["pIC50_calc"] = -np.log10(df["IC50_nM"] * 1e-9)
    has_p = df["pChEMBL"].notna()
    disagree = int((has_p & ((df["pChEMBL"] - df["pIC50_calc"]).abs() > cfg["pchembl_tol"])).sum())
    df["pIC50"] = np.where(has_p, df["pChEMBL"], df["pIC50_calc"])
    log["pchembl_used"] = int(has_p.sum()); log["pchembl_disagree"] = disagree

    df = df[df["pIC50"].between(cfg["pic50_min"], cfg["pic50_max"])].copy(); log["pic50_range"] = len(df)

    df["SMILES"] = df["SMILES"].apply(standardise_smiles)
    df = df.dropna(subset=["SMILES"]); log["standardised"] = len(df)

    grp = df.groupby("SMILES")["pIC50"]
    rng = grp.transform("max") - grp.transform("min")
    n_bad = int(df.loc[rng > cfg["replicate_range_max"], "SMILES"].nunique())
    df = df[rng <= cfg["replicate_range_max"]].copy()
    final = df.groupby("SMILES", as_index=False).agg(
        ChEMBL_ID=("ChEMBL_ID", "first"), pIC50=("pIC50", "median"))[["ChEMBL_ID", "SMILES", "pIC50"]]
    log["unique"] = len(final); log["discarded_range"] = n_bad

    meta = {"target_id": cfg["id"], "chembl_id": cfg["chembl_id"], "name": cfg["name"],
            "endpoint": "pIC50", "organism": cfg["organism"] if cfg["filter_organism"] else "any",
            "n_unique": len(final), "row_counts": log,
            "pic50_min": round(float(final["pIC50"].min()), 3) if len(final) else None,
            "pic50_max": round(float(final["pIC50"].max()), 3) if len(final) else None,
            "curated_utc": datetime.datetime.utcnow().isoformat() + "Z"}
    return final, meta

# ============================================================
#   MATRIX HELPERS
# ============================================================
def _cont_values(frame, cont_cols):
    return (frame[cont_cols].apply(pd.to_numeric, errors="coerce")
            .replace([np.inf, -np.inf], np.nan).fillna(0).clip(-1e6, 1e6).values)

def _fit_scaler(frame, cont_cols):
    s = StandardScaler()
    if cont_cols:
        s.fit(_cont_values(frame, cont_cols))
    return s

def _matrix(frame, scaler, cont_cols, bit_cols):
    cont = _cont_values(frame, cont_cols) if cont_cols else np.empty((len(frame), 0))
    bits = frame[bit_cols].fillna(0).astype(np.float64).values if bit_cols else np.empty((len(frame), 0))
    cont = scaler.transform(cont) if cont_cols else cont
    return np.hstack([cont, bits])

def make_models(cfg):
    rs = cfg["random_state"]
    return {
        "RandomForest":     RandomForestRegressor(n_estimators=500, max_features="sqrt",
                                                  min_samples_leaf=2, n_jobs=-1, random_state=rs),
        "ExtraTrees":       ExtraTreesRegressor(n_estimators=500, max_features="sqrt",
                                                min_samples_leaf=2, n_jobs=-1, random_state=rs),
        "GradientBoosting": GradientBoostingRegressor(n_estimators=300, learning_rate=0.05,
                                                      max_depth=4, subsample=0.8, random_state=rs),
        "RidgeCV":          RidgeCV(alphas=np.logspace(-1, 4, 24)),
    }

def _scaffold(smi):
    try:
        m = Chem.MolFromSmiles(smi)
        return MurckoScaffold.MurckoScaffoldSmiles(mol=m, includeChirality=False) if m else "invalid"
    except Exception:
        return "invalid"

def _split4(frame, seed):
    sc = frame["_scaffold"].unique().copy()
    rng = np.random.RandomState(seed); rng.shuffle(sc)
    a, b, c = int(0.70 * len(sc)), int(0.80 * len(sc)), int(0.90 * len(sc))
    pick = lambda s: frame[frame["_scaffold"].isin(set(s))].index.to_numpy()
    return pick(sc[:a]), pick(sc[a:b]), pick(sc[b:c]), pick(sc[c:])

def _split3(frame, seed):
    sc = frame["_scaffold"].unique().copy()
    rng = np.random.RandomState(seed); rng.shuffle(sc)
    a, b = int(0.80 * len(sc)), int(0.90 * len(sc))
    pick = lambda s: frame[frame["_scaffold"].isin(set(s))].index.to_numpy()
    return pick(sc[:a]), pick(sc[a:b]), pick(sc[b:])

def _conformal_quantile(scores, confidence):
    n = len(scores)
    if n == 0:
        return float("nan")
    k = min(int(np.ceil((n + 1) * confidence)), n)
    return float(np.sort(scores)[k - 1])

def _corr_drop(Xdf, kept, thr, block=256):
    """Memory-safe equivalent of dropping any column that correlates > thr with an
       earlier column. Streams correlations in column-blocks instead of building the
       full p x p matrix (which is what OOMs on wide fingerprint sets)."""
    X = Xdf[kept].fillna(0).to_numpy(dtype=np.float32, copy=True)
    X -= X.mean(axis=0)
    norm = np.sqrt((X * X).sum(axis=0)); norm[norm == 0] = 1.0
    X /= norm                                   # unit-norm columns -> dot = Pearson r
    p = X.shape[1]
    drop = np.zeros(p, dtype=bool)
    for a in range(0, p, block):
        b = min(a + block, p)
        C = np.abs(X[:, :b].T @ X[:, a:b])      # (b, block) corr of earlier+block vs block
        for j in range(a, b):
            col = C[:j, j - a]                  # correlations with strictly-earlier columns
            if col.size and (col > thr).any():
                drop[j] = True
    return [kept[i] for i in range(p) if not drop[i]]

# ============================================================
#   PREDICTION CORE (shared by training-eval and serving)
# ============================================================
def _predict_core(smiles_list, A, ref_bvs_cache=None):
    """Expensive part done ONCE: featurise, build X, all base-model predictions,
       disagreement sigma, AD distance. Per-model results are cheap slices of this."""
    if ref_bvs_cache is None:
        ref_bvs_cache = [b for b in (ecfp4_bv(s) for s in A["ref_smiles"]) if b is not None]
    rows, ok_bv, parsed = [], [], []
    for smi in smiles_list:
        cs = standardise_smiles(smi)
        d, bv = (featurise(cs, A.get("rich_features", True)) if cs else (None, None))
        rows.append(d); ok_bv.append(bv); parsed.append(cs)

    def grab(cols):
        return np.array([[float(r.get(c, 0.0)) if r else 0.0 for c in cols] for r in rows], dtype=np.float64)
    cont = grab(A["cont_cols"]) if A["cont_cols"] else np.empty((len(rows), 0))
    bits = grab(A["bit_cols"]) if A["bit_cols"] else np.empty((len(rows), 0))
    cont = np.nan_to_num(cont, nan=0.0, posinf=0.0, neginf=0.0).clip(-1e6, 1e6)
    cont = A["scaler"].transform(cont) if A["cont_cols"] else cont
    X = np.hstack([cont, bits])

    order = A["model_order"]
    base = np.vstack([A["models"][n].predict(X) for n in order]) if len(rows) else np.empty((len(order), 0))
    ad_dist = np.array([np.nan if bv is None else knn_tanimoto_distance(bv, ref_bvs_cache, A["ad_k"])
                        for bv in ok_bv], dtype=float)
    lam = A.get("sigma_ad_lambda", 0.0)
    sigma = ((base.std(axis=0) if base.size else np.zeros(len(rows))) + A.get("sigma_floor", 0.0)) \
        * (1.0 + lam * np.nan_to_num(ad_dist, nan=0.0))
    valid = [not np.isnan(d) for d in ad_dist]
    in_ad = [(not np.isnan(d)) and (d <= A["ad_threshold"]) for d in ad_dist]
    return {"base": base, "order": order, "sigma": sigma, "ad_dist": ad_dist,
            "in_ad": in_ad, "valid": valid, "parsed": parsed}

def list_models(A):
    """Names the chemist can choose from (base models + ensembles), best first."""
    names = list(A["model_order"]) + ["Ensemble (avg)", "Ensemble (weighted)"]
    return [A["best_name"]] + [n for n in names if n != A["best_name"]]

def _point(core, A, model_name):
    base, order = core["base"], core["order"]
    if model_name == "Ensemble (avg)":
        return base.mean(axis=0)
    if model_name == "Ensemble (weighted)":
        return np.average(base, axis=0, weights=A["weights"])
    return base[order.index(model_name)]

def _conformal_for(A, model_name):
    by = A.get("conformal_by_model", {})
    return by.get(model_name, A.get("conformal"))

def predict_from_assets(smiles_list, A, model_name=None, ref_bvs_cache=None, core=None):
    """Predict with the chosen model (default = best). Intervals use that model's
       own conformal calibration, so any model the chemist picks stays valid."""
    model_name = model_name or A["best_name"]
    if core is None:
        core = _predict_core(smiles_list, A, ref_bvs_cache)
    yp = _point(core, A, model_name) if core["base"].size else np.array([])
    sigma = core["sigma"]
    out = pd.DataFrame({
        "Input_SMILES": smiles_list, "Standardised_SMILES": core["parsed"], "Parsed_OK": core["valid"],
        f"Predicted_{A['endpoint']}": np.round(yp, 3), "Sigma": np.round(sigma, 3),
        "AD_distance": np.round(core["ad_dist"], 3),
        "In_AD": core["in_ad"], "Model": model_name, "Target": A["name"], "Target_ChEMBL": A["chembl_id"],
    })
    conf = _conformal_for(A, model_name)
    if conf and len(yp):
        lvl = int(round(conf["confidence"] * 100))
        out[f"Lower_{lvl}"] = np.round(yp - conf["q_lower"] * sigma, 3)
        out["PI_low"]  = np.round(yp - conf["q_interval"] * sigma, 3)
        out["PI_high"] = np.round(yp + conf["q_interval"] * sigma, 3)
    return out

# ============================================================
#   TRAINING
# ============================================================
def train(cfg, df):
    """Curated df -> (asset, metrics). Leak-free; raises on degenerate splits."""
    rich = cfg["rich_features"]

    feat_rows, bvs, keep = [], [], []
    for i, smi in enumerate(df["SMILES"].tolist()):
        d, bv = featurise(smi, rich)
        if d is not None and bv is not None:
            feat_rows.append(d); bvs.append(bv); keep.append(i)
    df = df.iloc[keep].reset_index(drop=True)
    F = pd.DataFrame(feat_rows)
    for c in F.columns:
        if c.startswith(BIT_PREFIXES):
            F[c] = pd.to_numeric(F[c], errors="coerce").fillna(0).astype("int8")
        else:
            F[c] = pd.to_numeric(F[c], errors="coerce")
    F = F.replace([np.inf, -np.inf], np.nan)
    full = pd.concat([df.reset_index(drop=True), F], axis=1)
    full["_bv"] = np.arange(len(full))
    full["_scaffold"] = full["SMILES"].apply(_scaffold)

    tr, va, ca, te = _split4(full, cfg["random_state"])
    for nm, idx in [("train", tr), ("val", va), ("calib", ca), ("test", te)]:
        if len(idx) < 2:
            raise ValueError(f"split '{nm}' has {len(idx)} compounds — dataset too small for {cfg['id']}")

    non_feat = {"ChEMBL_ID", "SMILES", "pIC50", "_scaffold", "_bv"}
    feats = [c for c in full.columns if c not in non_feat]
    Xtr = full.loc[tr, feats]
    kept = Xtr.columns[VarianceThreshold(0.0).fit(Xtr.fillna(0)).get_support()].tolist()
    if len(kept) <= cfg["max_corr_feats"]:
        feats_final = _corr_drop(Xtr, kept, cfg["corr_threshold"])
    else:
        feats_final = kept
    cont_cols = [f for f in feats_final if not f.startswith(BIT_PREFIXES)]
    bit_cols = [f for f in feats_final if f.startswith(BIT_PREFIXES)]

    y = lambda idx: full.loc[idx, "pIC50"].values

    # ---- selection: fit train, choose on val ----
    sA = _fit_scaler(full.loc[tr], cont_cols)
    Xtr_m = _matrix(full.loc[tr], sA, cont_cols, bit_cols)
    Xva_m = _matrix(full.loc[va], sA, cont_cols, bit_cols)
    mv = make_models(cfg); vp = {}
    for n, m in mv.items():
        m.fit(Xtr_m, y(tr)); vp[n] = m.predict(Xva_m)
    vr = {n: r2_score(y(va), vp[n]) for n in mv}
    w = np.array([max(vr[n], 0.0) for n in mv]); weights = w / w.sum() if w.sum() > 0 else np.ones(len(mv)) / len(mv)
    sv = np.vstack([vp[n] for n in mv])
    vr["Ensemble (avg)"] = r2_score(y(va), sv.mean(axis=0))
    vr["Ensemble (weighted)"] = r2_score(y(va), np.average(sv, axis=0, weights=weights))
    best = max(vr, key=vr.get)

    # ---- refit on train+val ----
    tv = np.concatenate([tr, va])
    sB = _fit_scaler(full.loc[tv], cont_cols)
    Xtv = _matrix(full.loc[tv], sB, cont_cols, bit_cols)
    mf = make_models(cfg)
    for n, m in mf.items():
        m.fit(Xtv, y(tv))

    # ---- AD on train+val ----
    ref_smiles = full.loc[tv, "SMILES"].tolist()
    ref_bvs = [bvs[int(j)] for j in full.loc[tv, "_bv"].values]
    rd = np.array([knn_tanimoto_distance(b, ref_bvs, cfg["ad_k"], drop_self=True) for b in ref_bvs])
    ad_thr = float(rd.mean() + cfg["ad_z"] * rd.std())
    ad_cap = float(min(np.percentile(rd, 99), 0.99))
    if ad_thr >= ad_cap:
        ad_thr = ad_cap

    # ---- conformal calibration PER candidate model (so any chosen model is valid) ----
    order = list(mf.keys())
    Xca = _matrix(full.loc[ca], sB, cont_cols, bit_cols)
    bc = np.vstack([mf[n].predict(Xca) for n in order])
    cal_bvs = [bvs[int(j)] for j in full.loc[ca, "_bv"].values]
    cal_dist = np.array([knn_tanimoto_distance(b, ref_bvs, cfg["ad_k"]) for b in cal_bvs])
    sig_ca = (bc.std(axis=0) + cfg["sigma_floor"]) * (1.0 + cfg["sigma_ad_lambda"] * cal_dist)
    conf = cfg["conformal_confidence"]

    candidates = order + ["Ensemble (avg)", "Ensemble (weighted)"]
    def _cal_pred(name):
        if name == "Ensemble (avg)":
            return bc.mean(axis=0)
        if name == "Ensemble (weighted)":
            return np.average(bc, axis=0, weights=weights)
        return bc[order.index(name)]
    conformal_by_model = {}
    for name in candidates:
        yhat = _cal_pred(name)
        conformal_by_model[name] = {
            "confidence": conf, "sigma_floor": cfg["sigma_floor"],
            "q_interval": _conformal_quantile(np.abs(y(ca) - yhat) / sig_ca, conf),
            "q_lower": _conformal_quantile((yhat - y(ca)) / sig_ca, conf)}

    asset = {
        "target_id": cfg["id"], "chembl_id": cfg["chembl_id"], "name": cfg["name"], "endpoint": "pIC50",
        "best_name": best, "models": mf, "weights": weights, "model_order": order,
        "scaler": sB, "final_features": feats_final, "cont_cols": cont_cols, "bit_cols": bit_cols,
        "ad_k": cfg["ad_k"], "ad_threshold": ad_thr, "ref_smiles": ref_smiles,
        "rich_features": rich, "sigma_floor": cfg["sigma_floor"], "sigma_ad_lambda": cfg["sigma_ad_lambda"],
        "conformal_by_model": conformal_by_model, "conformal": conformal_by_model[best],
    }

    # ---- evaluate ALL candidates on the held-out TEST set (one featurisation) ----
    core = _predict_core(full.loc[te, "SMILES"].tolist(), asset, ref_bvs_cache=ref_bvs)
    yt = y(te)
    in_ad = np.array(core["in_ad"], dtype=bool)
    metrics_by_model, report_models = {}, {}
    for name in candidates:
        ypm = _point(core, asset, name)
        cm = conformal_by_model[name]
        pil = ypm - cm["q_interval"] * core["sigma"]; pih = ypm + cm["q_interval"] * core["sigma"]
        low = ypm - cm["q_lower"] * core["sigma"]
        cov = float(np.mean((yt >= pil) & (yt <= pih)))
        rho = spearmanr(yt, ypm).correlation
        tp = 100.0 * float((yt < yt[int(np.argmax(low))]).mean())   # rank-by-lower-bound top pick
        metrics_by_model[name] = {
            "val_r2": round(float(vr[name]), 4),
            "test_r2": round(float(r2_score(yt, ypm)), 4),
            "test_rmse": round(float(np.sqrt(mean_squared_error(yt, ypm))), 4),
            "test_mae": round(float(mean_absolute_error(yt, ypm)), 4),
            "spearman": round(float(rho), 4),
            "top_pick_pct": round(tp, 1),
            "conformal_coverage": round(cov, 3),
        }
        report_models[name] = {"test_pred": np.round(ypm, 3).tolist(),
                               "lower": np.round(low, 3).tolist(),
                               "pi_low": np.round(pil, 3).tolist(),
                               "pi_high": np.round(pih, 3).tolist()}
    asset["metrics_by_model"] = metrics_by_model

    # shipped-model headline numbers (for the gate + registry)
    bm = metrics_by_model[best]
    yp = np.array(report_models[best]["test_pred"])
    rmse_in = float(np.sqrt(mean_squared_error(yt[in_ad], yp[in_ad]))) if in_ad.any() else float("nan")
    rmse_out = float(np.sqrt(mean_squared_error(yt[~in_ad], yp[~in_ad]))) if (~in_ad).any() else float("nan")

    # ---- ranking stability over repeated 3-way scaffold splits ----
    rhos, picks = [], []
    for rep in range(cfg["n_cv_repeats"]):
        a, b, c = _split3(full, cfg["random_state"] + 100 + rep)
        if min(len(a), len(b), len(c)) < 2:
            continue
        s = _fit_scaler(full.loc[a], cont_cols)
        Xa, Xb = _matrix(full.loc[a], s, cont_cols, bit_cols), _matrix(full.loc[b], s, cont_cols, bit_cols)
        mm = make_models(cfg); pv = {}
        for n, m in mm.items():
            m.fit(Xa, y(a)); pv[n] = m.predict(Xb)
        rr = {n: r2_score(y(b), pv[n]) for n in mm}
        ww = np.array([max(rr[n], 0.0) for n in mm]); ww = ww / ww.sum() if ww.sum() > 0 else np.ones(len(mm)) / len(mm)
        stv = np.vstack([pv[n] for n in mm])
        rr["Ensemble (avg)"] = r2_score(y(b), stv.mean(axis=0))
        rr["Ensemble (weighted)"] = r2_score(y(b), np.average(stv, axis=0, weights=ww))
        bn = max(rr, key=rr.get)
        ab = np.concatenate([a, b])
        s2 = _fit_scaler(full.loc[ab], cont_cols)
        Xab, Xc = _matrix(full.loc[ab], s2, cont_cols, bit_cols), _matrix(full.loc[c], s2, cont_cols, bit_cols)
        m2 = make_models(cfg)
        for n, m in m2.items():
            m.fit(Xab, y(ab))
        if bn == "Ensemble (avg)":
            pc = np.mean([m2[n].predict(Xc) for n in m2], axis=0)
        elif bn == "Ensemble (weighted)":
            pc = np.average([m2[n].predict(Xc) for n in m2], axis=0, weights=ww)
        else:
            pc = m2[bn].predict(Xc)
        yc = y(c)
        rhos.append(spearmanr(yc, pc).correlation)
        picks.append(100.0 * float((yc < yc[int(np.argmax(pc))]).mean()))

    metrics = {
        "n_compounds": int(len(full)),
        "n_train": int(len(tr)), "n_val": int(len(va)), "n_calib": int(len(ca)), "n_test": int(len(te)),
        "test_r2": bm["test_r2"], "test_rmse": bm["test_rmse"], "test_mae": bm["test_mae"],
        "spearman_mean": round(float(np.nanmean(rhos)), 4) if rhos else None,
        "spearman_std": round(float(np.nanstd(rhos)), 4) if rhos else None,
        "top_pick_pct_mean": round(float(np.nanmean(picks)), 1) if picks else None,
        "ad_coverage_pct": round(float(100 * in_ad.mean()), 1),
        "rmse_in_ad": round(rmse_in, 4), "rmse_out_ad": round(rmse_out, 4),
        "conformal_confidence": conf,
        "conformal_interval_coverage": bm["conformal_coverage"],
        "selected_model": best,
    }
    asset["training_metrics"] = metrics

    report_data = {
        "target_id": cfg["id"], "name": cfg["name"], "chembl_id": cfg["chembl_id"],
        "endpoint": "pIC50", "best_name": best, "confidence": conf,
        "n": {"train": int(len(tr)), "val": int(len(va)), "calib": int(len(ca)), "test": int(len(te)),
              "total": int(len(full))},
        "test_actual": np.round(yt, 3).tolist(),
        "in_ad": in_ad.tolist(),
        "test_smiles": full.loc[te, "SMILES"].tolist(),
        "metrics_by_model": metrics_by_model,
        "models": report_models,
        "stability": {"spearman_mean": metrics["spearman_mean"], "spearman_std": metrics["spearman_std"],
                      "top_pick_pct_mean": metrics["top_pick_pct_mean"]},
    }
    return asset, metrics, report_data

# ============================================================
#   QUALITY GATE
# ============================================================
def gate(cfg, m):
    """Ranking quality decides live/experimental. Interval coverage is a SEPARATE
       honesty label ('calibrated' vs 'approximate'), not a blocker — because this
       is a ranking tool: the ranking is the product, the interval is context.
       Returns (status, reasons, interval_status)."""
    reasons = []
    if m["n_compounds"] < cfg["gate_min_compounds"]:
        reasons.append(f"too few compounds ({m['n_compounds']} < {cfg['gate_min_compounds']})")
    if m["spearman_mean"] is None or m["spearman_mean"] < cfg["gate_min_spearman"]:
        reasons.append(f"ranking too weak (Spearman {m['spearman_mean']} < {cfg['gate_min_spearman']})")
    if cfg["gate_require_ad_discriminates"]:
        ri, ro = m["rmse_in_ad"], m["rmse_out_ad"]
        if not (np.isnan(ro) or (ri < ro)):
            reasons.append("AD does not discriminate (in-domain error not lower)")
    status = "live" if not reasons else "experimental"

    cov, conf = m["conformal_interval_coverage"], m["conformal_confidence"]
    interval_status = "calibrated" if (cov is not None and cov >= conf - cfg["gate_conformal_tolerance"]) \
        else "approximate"
    return status, reasons, interval_status

# ============================================================
#   SCREENING (serve side) — rank by conformal lower bound
# ============================================================
def predict_stream(smiles_list, asset, model_name=None, batch=2000, progress=False):
    """Predict in fixed-size batches so peak memory does not grow with file size."""
    ref = [b for b in (ecfp4_bv(s) for s in asset["ref_smiles"]) if b is not None]
    parts, n = [], len(smiles_list)
    for start in range(0, n, batch):
        chunk = smiles_list[start:start + batch]
        parts.append(predict_from_assets(chunk, asset, model_name=model_name, ref_bvs_cache=ref))
        if progress:
            print(f"    scored {min(start + batch, n)}/{n}", end="\r")
    if progress:
        print()
    return pd.concat(parts, ignore_index=True) if parts \
        else predict_from_assets([], asset, model_name=model_name, ref_bvs_cache=ref)

def screen(asset, smiles_list, model_name=None, batch=2000, progress=False):
    model_name = model_name or asset["best_name"]
    res = predict_stream(smiles_list, asset, model_name=model_name, batch=batch, progress=progress)
    conf = _conformal_for(asset, model_name)
    lvl = int(round(conf["confidence"] * 100)) if conf else None
    sort_col = f"Lower_{lvl}" if conf else f"Predicted_{asset['endpoint']}"
    in_dom = res[res["In_AD"]].sort_values(sort_col, ascending=False).reset_index(drop=True)
    in_dom.insert(0, "Rank", np.arange(1, len(in_dom) + 1))
    out_dom = res[~res["In_AD"]].reset_index(drop=True)
    return in_dom, out_dom, sort_col