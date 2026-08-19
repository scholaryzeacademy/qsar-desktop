"""
============================================================
  CONFIDENCE TIERS  (serving/confidence.py)
============================================================
  HONESTY NOTE: the shipped models are AutoGluon TabularPredictors with
  a single fit/test split (see each target's run_metadata.json) — there
  is no per-compound calibration set, so no genuine per-compound
  conformal interval exists for them. Rather than fabricate one, the
  tier below is out-of-domain status + the target's own held-out TEST
  RMSE, labelled honestly as a test-set error, not a prediction
  interval. This is a deliberately more modest claim than a conformal
  bound would be — see CLAUDE.md's calibrated-honesty principle.
============================================================
"""

HIGH_RMSE = 0.5
MED_RMSE = 1.0


def tier(is_in_domain, test_rmse):
    """Returns (tier: 'high'|'med'|'low'|'out', label: str, basis: str)."""
    if not is_in_domain:
        return "out", "Outside training chemistry", "applicability_domain"
    if test_rmse is None:
        return "med", "Medium confidence (target test error unknown)", "unknown"
    if test_rmse <= HIGH_RMSE:
        return "high", f"High confidence (held-out test RMSE {test_rmse:.2f} pIC50)", "test_rmse"
    if test_rmse <= MED_RMSE:
        return "med", f"Medium confidence (held-out test RMSE {test_rmse:.2f} pIC50)", "test_rmse"
    return "low", f"Low confidence (held-out test RMSE {test_rmse:.2f} pIC50 — wide expected error)", "test_rmse"
