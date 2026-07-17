"""Featurisation parity tests (CLAUDE.md §12): a fixed SMILES must produce a
feature vector matching the model's training feature space by NAME, and
self_check() must catch naming/version drift loudly instead of silently
zero-filling columns (the #1 corruption risk per CLAUDE.md §5)."""
import pytest

from serving import featurize as F


def test_standardise_smiles_valid():
    assert F.standardise_smiles("CC(=O)Oc1ccccc1C(=O)O") is not None


def test_standardise_smiles_invalid_returns_none():
    assert F.standardise_smiles("not a smiles") is None


def test_compute_features_rejects_empty_molecule():
    # RDKit parses "" as a valid zero-atom Mol (not None) -- the zero-heavy-atom
    # rejection has to happen in compute_features(), not standardise_smiles().
    assert F.compute_features("") is None


def test_compute_features_produces_expected_column_families():
    cs = F.standardise_smiles("CC(=O)Oc1ccccc1C(=O)O")   # aspirin
    d = F.compute_features(cs)
    assert d is not None
    maccs = [k for k in d if k.startswith("MACCS_")]
    morgan = [k for k in d if k.startswith("Morgan_")]
    plain = [k for k in d if not k.startswith(("MACCS_", "Morgan_"))]
    assert len(maccs) == F.N_MACCS
    assert len(morgan) == F.N_MORGAN
    assert len(plain) == F.N_DESCRIPTORS
    # every value must be finite (no NaN/inf leaking out of a single bad descriptor)
    assert all(v == v and abs(v) != float("inf") for v in d.values())


def test_self_check_passes_on_real_naming_convention():
    cols = ["MaxAbsEStateIndex", "qed", "MACCS_8", "Morgan_0", "Morgan_2047", "chemprop_pred"]
    F.self_check(cols)   # must not raise


def test_self_check_fails_loudly_on_naming_drift():
    """Guards against exactly the bug already found once in this codebase:
       pipeline.py assumed an 'ECFP4_' fingerprint prefix but the real
       buckets use 'Morgan_' — self_check must catch that class of mismatch."""
    with pytest.raises(AssertionError):
        F.self_check(["ECFP4_0", "ECFP4_1", "chemprop_pred"])


def test_featurise_batch_matches_target_feature_width(target):
    df, std, ok = F.featurise_batch(["CC(=O)Oc1ccccc1C(=O)O", "not a smiles"],
                                     target.desc_feature_columns)
    assert list(df.columns) == target.desc_feature_columns
    assert df.shape == (2, len(target.desc_feature_columns))
    assert ok == [True, False]
    assert std[1] is None
    assert not df.isna().any().any()   # fillna(0) must have run
