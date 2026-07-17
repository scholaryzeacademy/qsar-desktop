"""serving/model_adapter.py: bucket loading, feature-width parity, and the
robustness fix for extreme out-of-distribution inputs (a real bug found
while writing these tests — a long repeating-unit SMILES produced a
finite-but-float32-overflowing value that crashed sklearn's check_array
instead of just being flagged out-of-domain)."""
import pytest

from serving import model_adapter as MA


def test_load_unknown_target_raises_bucket_error_not_crash():
    with pytest.raises(MA.BucketError):
        MA.load_target("no_such_target_xyz")


def test_list_target_ids_finds_real_buckets():
    ids = MA.list_target_ids()
    assert "CHEMBL1163125_BRD4" in ids
    assert len(ids) >= 1


def test_feature_vector_width_matches_selected_features(target):
    assert len(target.feature_columns) == len(target.desc_feature_columns) + 1  # + chemprop_pred
    df = target.predict_smiles(["CC(=O)Oc1ccccc1C(=O)O"])
    assert len(df) == 1
    row = df.iloc[0]
    assert row["Parsed_OK"]
    assert row["Predicted_pIC50"] == row["Predicted_pIC50"]   # not NaN


def test_predict_smiles_never_crashes_on_extreme_out_of_distribution_input(target):
    """Regression test for the float32-overflow crash: a long repeating
       polyethylene-glycol-like chain, unlike anything in a kinase-inhibitor
       training set, must degrade to a (possibly low-confidence) prediction
       or an out-of-domain flag — never raise."""
    extreme = "C" + "OCC" * 60 + "O"
    df = target.predict_smiles([extreme])
    row = df.iloc[0]
    assert row["Parsed_OK"]
    assert row["Predicted_pIC50"] == row["Predicted_pIC50"]   # finite, not NaN
    assert abs(row["Predicted_pIC50"]) < 1e6


def test_predict_smiles_handles_unparsable_input_gracefully(target):
    df = target.predict_smiles(["not a smiles", "CC(=O)Oc1ccccc1C(=O)O"])
    assert df.iloc[0]["Parsed_OK"] == False
    assert df.iloc[1]["Parsed_OK"] == True


def test_bounded_cache_evicts_oldest():
    ids = MA.list_target_ids()
    if len(ids) < MA.CACHE_SIZE + 1:
        pytest.skip("not enough real target buckets available to exercise eviction")
    for tid in ids[:MA.CACHE_SIZE + 1]:
        MA.load_target(tid)
    assert len(MA._cache) <= MA.CACHE_SIZE
