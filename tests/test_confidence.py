from serving import confidence as CONF


def test_out_of_domain_tier():
    tier, label, basis = CONF.tier(False, 0.1)
    assert tier == "out"
    assert basis == "applicability_domain"


def test_unknown_rmse_is_medium_not_fabricated():
    tier, label, basis = CONF.tier(True, None)
    assert tier == "med"
    assert basis == "unknown"
    assert "unknown" in label


def test_low_rmse_is_high_confidence():
    tier, label, basis = CONF.tier(True, 0.3)
    assert tier == "high"
    assert basis == "test_rmse"


def test_high_rmse_is_low_confidence():
    tier, label, basis = CONF.tier(True, 2.5)
    assert tier == "low"
