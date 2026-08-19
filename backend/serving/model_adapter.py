"""
============================================================
  MODEL ADAPTER  (serving/model_adapter.py)
============================================================
  The ONLY module in the app that knows the shipped target-bucket
  format. Everything else (app.py, analysis.py, screen.py) calls
  load_target()/Target.* and never imports AutoGluon or Chemprop
  directly (CLAUDE.md §6 isolation boundary).

  Real bucket layout (models/<target_id>/, see CLAUDE.md §5):
    chosen_model/            AutoGluon TabularPredictor
    _cache/chemprop_final.ckpt   Chemprop D-MPNN checkpoint
    selected_features.csv    ordered feature list, ENDS with 'chemprop_pred'
    Data/fit.csv             training feature matrix -> AD mean/std
    metrics.xlsx / run_metadata.json   headline metrics (real numbers only)
    Plots/*.png               the 9 standard QSAR plots

  Two-stage inference (confirmed from run_log.txt / predict.py, NOT just
  the simplified 'RDKit + MACCS + Morgan' description in CLAUDE.md §5):
    1. Chemprop D-MPNN forward pass on the SMILES graph -> 'chemprop_pred'
    2. That value is appended as one more tabular feature and the full
       vector is fed to the AutoGluon stacked ensemble -> final pIC50.
  Both stages are INFERENCE ONLY on pre-trained checkpoints — no training
  happens here, consistent with CLAUDE.md §1.

  CPU-only: torch/lightning are forced to accelerator='cpu' regardless of
  what's on the machine, and thread counts are capped so this app never
  needs or touches a GPU (CLAUDE.md §4).
============================================================
"""
import os
import json
import threading
import collections

os.environ.setdefault("OMP_NUM_THREADS", os.environ.get("PHYTO_CPU_THREADS", "4"))
os.environ.setdefault("MKL_NUM_THREADS", os.environ.get("PHYTO_CPU_THREADS", "4"))
os.environ.setdefault("OPENBLAS_NUM_THREADS", os.environ.get("PHYTO_CPU_THREADS", "4"))
os.environ.setdefault("TQDM_DISABLE", "1")
os.environ.setdefault("PYTORCH_LIGHTNING_DISABLE_PROGRESS_BAR", "1")

import logging
for _n in ("lightning.pytorch", "pytorch_lightning", "lightning", "chemprop", "autogluon"):
    logging.getLogger(_n).setLevel(logging.ERROR)

import numpy as np
import pandas as pd

from . import featurize as F
from . import applicability as AD
from . import confidence as CONF

TARGETS_DIR = os.environ.get("TARGETS_DIR", "models")
CACHE_SIZE = int(os.environ.get("PHYTO_MODEL_CACHE_SIZE", "2"))  # bounded: buckets are large

_lock = threading.Lock()
_cache = collections.OrderedDict()   # target_id -> Target, LRU order


class BucketError(Exception):
    """Raised when a target bucket is missing required files or fails to load."""


def _bucket_dir(target_id):
    return os.path.join(TARGETS_DIR, target_id)


def _require(path, what):
    if not os.path.exists(path):
        raise BucketError(f"missing {what}: {path}")
    return path


def list_target_ids():
    """Target ids with a structurally-complete bucket (does not load models)."""
    if not os.path.isdir(TARGETS_DIR):
        return []
    out = []
    for tid in sorted(os.listdir(TARGETS_DIR)):
        bdir = _bucket_dir(tid)
        if not os.path.isdir(bdir):
            continue
        needed = ["chosen_model", "selected_features.csv", os.path.join("Data", "fit.csv")]
        if all(os.path.exists(os.path.join(bdir, n)) for n in needed):
            out.append(tid)
    return out


def get_metrics(target_id):
    """Cheap metrics-only read for a single target (no model loading)."""
    return _load_metrics(_bucket_dir(target_id), target_id)


def list_targets_meta():
    """Cheap listing for UI/API use: reads run_metadata.json/metrics.xlsx only
       — does NOT load the AutoGluon predictor or Chemprop checkpoint, so
       listing all targets stays fast even though each bucket is large."""
    return [{"target_id": tid, "metrics": _load_metrics(_bucket_dir(tid), tid)}
            for tid in list_target_ids()]


def _load_metrics(bdir, target_id):
    """run_metadata.json is the canonical source (plain JSON, reliable field
       names); metrics.xlsx is used only if that's missing. Every value here
       traces to a real bucket file — nothing is invented (CALIBRATED HONESTY)."""
    meta_path = os.path.join(bdir, "run_metadata.json")
    if os.path.exists(meta_path):
        with open(meta_path) as f:
            meta = json.load(f)
        m = dict(meta.get("metrics", {}))
        m["timestamp"] = meta.get("timestamp")
        m["best_model"] = meta.get("best_model", m.get("Best_Model"))
        m["tropsha_detail"] = meta.get("tropsha_detail")
        m["counts"] = meta.get("counts")
        return m
    xlsx_path = os.path.join(bdir, "metrics.xlsx")
    if os.path.exists(xlsx_path):
        return pd.read_excel(xlsx_path).iloc[0].to_dict()
    return {}


def _load_plots(bdir):
    pdir = os.path.join(bdir, "Plots")
    if not os.path.isdir(pdir):
        return {}
    return {os.path.splitext(n)[0]: os.path.join(pdir, n)
            for n in sorted(os.listdir(pdir)) if n.lower().endswith(".png")}


def _load_mpnn(ckpt_path):
    """Load the Chemprop checkpoint once; the caller caches the result on the
       Target so repeated predict_smiles() calls don't re-read it from disk."""
    from chemprop import models
    return models.MPNN.load_from_checkpoint(ckpt_path, map_location="cpu")


def _chemprop_predict(mpnn, std_smiles, batch_size=128):
    """Run an already-loaded Chemprop model on standardised SMILES.
       Forced CPU (accelerator='cpu') — this app never requires a GPU."""
    import torch
    from lightning import pytorch as pl
    from chemprop import data, featurizers

    feat = featurizers.SimpleMoleculeMolGraphFeaturizer()
    pts = [data.MoleculeDatapoint.from_smi(s, np.array([0.0])) for s in std_smiles]
    dset = data.MoleculeDataset(pts, feat)
    loader = data.build_dataloader(dset, batch_size=batch_size, shuffle=False, num_workers=0)
    trainer = pl.Trainer(accelerator="cpu", devices=1, logger=False,
                          enable_progress_bar=False, enable_checkpointing=False)
    with torch.inference_mode():
        preds = trainer.predict(mpnn, loader)
    return np.concatenate([p.numpy().ravel() for p in preds])


class Target:
    """One loaded target bucket. Isolates AutoGluon + Chemprop entirely."""

    def __init__(self, target_id):
        self.target_id = target_id
        self.bdir = _bucket_dir(target_id)
        _require(self.bdir, "target bucket")

        model_dir = _require(os.path.join(self.bdir, "chosen_model"), "chosen_model/")
        feats_csv = _require(os.path.join(self.bdir, "selected_features.csv"), "selected_features.csv")
        fit_csv = _require(os.path.join(self.bdir, "Data", "fit.csv"), "Data/fit.csv")
        self.ckpt_path = os.path.join(self.bdir, "_cache", "chemprop_final.ckpt")
        if not os.path.exists(self.ckpt_path):
            raise BucketError(f"missing Chemprop checkpoint: {self.ckpt_path}")

        self.feature_columns = pd.read_csv(feats_csv)["Feature"].tolist()
        self.desc_feature_columns = [c for c in self.feature_columns if c != "chemprop_pred"]
        if "chemprop_pred" not in self.feature_columns:
            raise BucketError(f"'{target_id}': selected_features.csv has no 'chemprop_pred' column "
                              f"— this adapter assumes the two-stage Chemprop+AutoGluon bucket format.")

        # startup self-check: featurizer must be able to produce every named
        # descriptor/fingerprint column this target's model expects.
        F.self_check(self.feature_columns)

        fit_df = pd.read_csv(fit_csv)
        self.ad_mean, self.ad_std = AD.fit_ad_params(fit_df, self.feature_columns)
        self.ad_threshold = AD.DEFAULT_Z_THRESHOLD

        from autogluon.tabular import TabularPredictor
        self.predictor = TabularPredictor.load(model_dir, require_version_match=False)

        # bonus parity check: everything AutoGluon actually asks for at predict()
        # time must be a subset of what we know how to produce. AutoGluon may
        # legitimately want FEWER columns than selected_features.csv lists (its
        # own internal preprocessing drops some), which is harmless — we just
        # feed it the full reindexed frame and it ignores the rest. It must
        # never want a column we DON'T produce; that's the real corruption signal.
        try:
            expected = set(self.predictor.features())
            unknown = expected - set(self.feature_columns)
            if unknown:
                raise BucketError(
                    f"'{target_id}': AutoGluon predictor expects {len(unknown)} feature column(s) "
                    f"not present in selected_features.csv (e.g. {sorted(unknown)[:8]}) — "
                    f"refusing to serve possibly-corrupted predictions.")
        except AttributeError:
            pass  # older/newer AutoGluon without .features(); self_check() above still applies

        self.name = target_id
        self.metrics = _load_metrics(self.bdir, target_id)
        self.plots = _load_plots(self.bdir)
        self._mpnn = None                      # lazy-loaded, cached on first predict
        self._predict_lock = threading.Lock()

    # ---- CLAUDE.md §6 contract ----
    def predict(self, feature_df):
        """feature_df: DataFrame already ordered/filled to self.feature_columns
           (incl. chemprop_pred). Returns np.ndarray of predicted pIC50.
           Clips to a safe finite range, not just NaN/inf: an extreme
           out-of-distribution molecule (e.g. a long repeating chain) can
           push a raw descriptor or the Chemprop forward pass to a value
           that is technically finite in float64 but overflows float32
           once AutoGluon's sklearn child models cast to it — sklearn then
           raises instead of just predicting badly. A molecule this unusual
           should come back flagged out-of-domain, never crash the request."""
        X = feature_df.reindex(columns=self.feature_columns)
        X = X.replace([np.inf, -np.inf], np.nan).fillna(0).clip(-1e6, 1e6)
        return self.predictor.predict(X).to_numpy()

    def applicability(self, feature_df):
        """feature_df: same shape as predict(). Returns (in_domain: bool[], z: float[])."""
        X = feature_df.reindex(columns=self.feature_columns).apply(pd.to_numeric, errors="coerce")
        X = X.replace([np.inf, -np.inf], np.nan).fillna(0).clip(-1e6, 1e6)
        z = AD.ad_z(X.to_numpy(dtype=float), self.ad_mean, self.ad_std)
        return AD.in_domain(z, self.ad_threshold), z

    # ---- convenience: the endpoint the rest of the app actually calls ----
    def predict_smiles(self, smiles_list):
        """Full pipeline: standardise -> featurise -> Chemprop -> AutoGluon ->
           AD -> confidence. Returns a DataFrame, one row per input SMILES."""
        desc_df, std_smiles, parsed_ok = F.featurise_batch(smiles_list, self.desc_feature_columns)

        cp = np.zeros(len(smiles_list), dtype=float)
        ok_idx = [i for i, ok in enumerate(parsed_ok) if ok]
        if ok_idx:
            with self._predict_lock:   # Chemprop/Lightning trainer isn't re-entrant-safe
                if self._mpnn is None:
                    self._mpnn = _load_mpnn(self.ckpt_path)
                cp_vals = _chemprop_predict(self._mpnn, [std_smiles[i] for i in ok_idx])
            for j, i in enumerate(ok_idx):
                cp[i] = cp_vals[j]

        full = desc_df.copy()
        full["chemprop_pred"] = cp
        full = full.reindex(columns=self.feature_columns).fillna(0)

        yp = np.full(len(smiles_list), np.nan)
        z = np.full(len(smiles_list), np.nan)
        in_dom = np.zeros(len(smiles_list), dtype=bool)
        if ok_idx:
            sub = full.iloc[ok_idx]
            yp_ok = self.predict(sub)
            in_dom_ok, z_ok = self.applicability(sub)
            for j, i in enumerate(ok_idx):
                yp[i] = yp_ok[j]; z[i] = z_ok[j]; in_dom[i] = bool(in_dom_ok[j])

        rmse = self.metrics.get("RMSE_Test")
        tiers = [CONF.tier(bool(d), rmse) if ok else ("na", "Could not parse SMILES", "n/a")
                 for d, ok in zip(in_dom, parsed_ok)]

        return pd.DataFrame({
            "Input_SMILES": smiles_list,
            "Standardised_SMILES": std_smiles,
            "Parsed_OK": parsed_ok,
            "Predicted_pIC50": np.round(yp, 3),
            "AD_z": np.round(z, 3),
            "In_AD": in_dom,
            "Confidence": [t[0] for t in tiers],
            "Confidence_Label": [t[1] for t in tiers],
            "Confidence_Basis": [t[2] for t in tiers],
        })


def load_target(target_id):
    """Load (or fetch from the bounded LRU cache) a Target. Raises BucketError
       with a clear reason if the bucket is missing/incomplete — callers turn
       that into 'target unavailable', never a crash."""
    with _lock:
        if target_id in _cache:
            _cache.move_to_end(target_id)
            return _cache[target_id]
    t = Target(target_id)   # loading is expensive; do it outside the lock
    with _lock:
        _cache[target_id] = t
        _cache.move_to_end(target_id)
        while len(_cache) > CACHE_SIZE:
            _cache.popitem(last=False)
    return t


def target_available(target_id):
    try:
        load_target(target_id)
        return True
    except Exception:
        return False
