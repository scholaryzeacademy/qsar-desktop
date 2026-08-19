"""
============================================================
  FEATURISE  (serving/featurize.py)
============================================================
  SMILES -> the same feature space the factory trained on:
  RDKit 2D descriptors (by name) + MACCS keys (MACCS_0..166) +
  Morgan/ECFP4 r=2, 2048 bits (Morgan_0..2047). See CLAUDE.md §5.

  This is the single most important correctness boundary in the app:
  a naming/order mismatch here silently corrupts every prediction.
  self_check() below is called once at startup per loaded target to
  catch drift immediately instead of shipping quietly-wrong numbers.
============================================================
"""
import numpy as np
import pandas as pd
from rdkit import Chem, RDLogger
from rdkit.Chem import Descriptors, MACCSkeys, rdFingerprintGenerator
from rdkit.Chem.MolStandardize import rdMolStandardize

RDLogger.DisableLog("rdApp.*")

_lfc = rdMolStandardize.LargestFragmentChooser()
_unch = rdMolStandardize.Uncharger()
_morgan = rdFingerprintGenerator.GetMorganGenerator(radius=2, fpSize=2048)
_DESCS = list(Descriptors.descList)

N_DESCRIPTORS = len(_DESCS)
N_MACCS = 167
N_MORGAN = 2048


def standardise_smiles(smi):
    """Same standardisation the factory used: RDKit cleanup + largest fragment
       + uncharge. Returns None if the SMILES cannot be parsed."""
    try:
        m = Chem.MolFromSmiles(smi)
        if m is None:
            return None
        m = rdMolStandardize.Cleanup(m)
        m = _lfc.choose(m)
        m = _unch.uncharge(m)
        return Chem.MolToSmiles(m)
    except Exception:
        return None


def compute_features(std_smiles):
    """standardised SMILES -> {feature_name: value} for the FULL feature space
       (before the factory's per-target column selection). Returns None if
       RDKit cannot parse it or featurisation fails outright. A single bad
       descriptor must never fail the whole molecule (matches factory
       robustness: per-descriptor guard, fallback 0.0)."""
    m = Chem.MolFromSmiles(std_smiles)
    if m is None or m.GetNumHeavyAtoms() == 0:
        return None
    d = {}
    for name, func in _DESCS:
        try:
            v = func(m)
            d[name] = v if v is not None and np.isfinite(v) else 0.0
        except Exception:
            d[name] = 0.0
    try:
        for i, b in enumerate(MACCSkeys.GenMACCSKeys(m)):
            d[f"MACCS_{i}"] = int(b)
        for i, b in enumerate(_morgan.GetFingerprint(m)):
            d[f"Morgan_{i}"] = int(b)
    except Exception:
        return None
    return d


def self_check(feature_columns):
    """Assert every named descriptor/fingerprint column a target's
       selected_features.csv asks for (everything except 'chemprop_pred',
       which is computed separately) is actually produced by
       compute_features(). Raises AssertionError on any naming/version drift
       instead of silently corrupting predictions with all-zero columns."""
    probe = compute_features(standardise_smiles("CC(=O)Oc1ccccc1C(=O)O"))  # aspirin
    assert probe is not None, "self_check: featurisation failed on a known-valid SMILES"
    needed = {c for c in feature_columns if c != "chemprop_pred"}
    missing = needed - set(probe.keys())
    assert not missing, (
        f"featurisation self-check FAILED: {len(missing)} expected feature column(s) "
        f"are not produced by compute_features() — e.g. {sorted(missing)[:8]}. "
        f"This means the featurizer no longer matches the model's training "
        f"feature space; predictions would be silently wrong. Do not serve "
        f"predictions until this is fixed."
    )


def featurise_batch(smiles_list, desc_feature_columns):
    """Standardise + featurise a batch, reindexed/ordered to
       desc_feature_columns (the target's selected features MINUS
       'chemprop_pred', which the caller fills in separately).
       Returns (DataFrame[len(smiles_list) x desc_feature_columns] filled
       with 0 where absent, standardised_smiles[list, None if unparsable],
       parsed_ok[bool list])."""
    std, rows, ok = [], [], []
    for smi in smiles_list:
        cs = standardise_smiles(smi)
        d = compute_features(cs) if cs else None
        std.append(cs)
        ok.append(d is not None)
        rows.append(d or {})
    df = pd.DataFrame(rows)
    df = df.replace([np.inf, -np.inf], np.nan)
    df = df.reindex(columns=desc_feature_columns)
    df = df.apply(pd.to_numeric, errors="coerce").fillna(0)
    return df, std, ok
