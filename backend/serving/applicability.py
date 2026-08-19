"""
============================================================
  APPLICABILITY DOMAIN  (serving/applicability.py)
============================================================
  CLAUDE.md §5: a compound is out-of-domain if the mean |z| over the
  target's training features exceeds a threshold (default 3.0). Mean
  and std are derived from the target's Data/fit.csv (the compounds
  actually used to fit the shipped model) since buckets do not ship
  separate AD parameters.

  Out-of-domain compounds are flagged and never given a trusted
  potency number — this gate is mandatory, not advisory.
============================================================
"""
import numpy as np
import pandas as pd

DEFAULT_Z_THRESHOLD = 3.0


def fit_ad_params(fit_df, feature_columns):
    """Per-feature mean/std from the training ('fit') set, ordered like
       feature_columns (the full selected_features list, incl. chemprop_pred
       if present in fit.csv)."""
    X = fit_df.reindex(columns=feature_columns).apply(pd.to_numeric, errors="coerce").fillna(0)
    mean = X.mean(axis=0).to_numpy(dtype=float)
    std = X.std(axis=0).to_numpy(dtype=float)
    std[std == 0] = 1e-8
    return mean, std


def ad_z(X, mean, std):
    """X: (n, p) ndarray ordered like feature_columns used to fit mean/std.
       Returns the mean |z-score| per row (0 = identical to training
       chemistry, larger = more extrapolated)."""
    z = np.abs((np.asarray(X, dtype=float) - mean) / std)
    return z.mean(axis=1)


def in_domain(z_scores, threshold=DEFAULT_Z_THRESHOLD):
    return np.asarray(z_scores) <= threshold
