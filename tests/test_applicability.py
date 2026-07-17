"""AD-gating test (CLAUDE.md §12): an obviously out-of-domain molecule is
flagged out-of-domain and receives no trusted potency.

A synthetic extreme feature vector is used for the boundary test rather than
searching for a 'weird' real molecule: this target's AD is a mean |z| over
2310 mostly-binary features, so a handful of extreme continuous descriptors
on an unusual real molecule can still average out below the threshold (this
was verified empirically) — a deliberately-constructed outlier makes the
gating logic itself deterministic and non-flaky to test."""
import numpy as np
import pandas as pd

from serving import applicability as AD


def test_fit_ad_params_shapes():
    fit = pd.DataFrame({"a": [1.0, 2.0, 3.0], "b": [10.0, 10.0, 10.0]})
    mean, std = AD.fit_ad_params(fit, ["a", "b"])
    assert mean.shape == (2,)
    assert std.shape == (2,)
    assert mean[0] == 2.0
    assert std[1] > 0   # zero-variance column must not produce a zero std (would div-by-zero)


def test_in_domain_at_training_mean():
    mean = np.array([1.0, 2.0, 3.0])
    std = np.array([1.0, 1.0, 1.0])
    z = AD.ad_z(mean.reshape(1, -1), mean, std)
    assert z[0] == 0.0
    assert AD.in_domain(z)[0]


def test_out_of_domain_far_from_training():
    mean = np.array([1.0, 2.0, 3.0])
    std = np.array([1.0, 1.0, 1.0])
    outlier = (mean + 20 * std).reshape(1, -1)
    z = AD.ad_z(outlier, mean, std)
    assert z[0] > AD.DEFAULT_Z_THRESHOLD
    assert not AD.in_domain(z)[0]


def test_target_applicability_flags_synthetic_outlier_out_of_domain(target):
    extreme = pd.DataFrame([target.ad_mean + 20 * target.ad_std], columns=target.feature_columns)
    in_dom, z = target.applicability(extreme)
    assert not in_dom[0]
    assert z[0] > target.ad_threshold


def test_target_applicability_flags_training_mean_in_domain(target):
    at_mean = pd.DataFrame([target.ad_mean], columns=target.feature_columns)
    in_dom, z = target.applicability(at_mean)
    assert in_dom[0]
    assert z[0] < 0.01


def test_out_of_domain_prediction_never_exposes_a_potency_number():
    """The API-boundary guarantee: CLAUDE.md §2 requires out-of-domain
       compounds to NOT receive a confident potency number, even if the
       model technically produced one internally."""
    from app import _rows
    df = pd.DataFrame([{
        "Input_SMILES": "C", "Standardised_SMILES": "C", "Parsed_OK": True,
        "Predicted_pIC50": 9.999, "AD_z": 50.0, "In_AD": False,
        "Confidence": "out", "Confidence_Label": "Outside training chemistry",
        "Confidence_Basis": "applicability_domain",
    }])
    rows = _rows(df)
    assert rows[0]["in_domain"] is False
    assert rows[0]["predicted_pIC50"] is None   # never leaked, despite the raw model output existing
