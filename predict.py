"""
=============================================================================
  PREDICT  --  use a trained target model on NEW molecules
=============================================================================
  Wires the two saved pieces together automatically:
    1. Chemprop graph-net  -> produces the 'chemprop_pred' feature
    2. AutoGluon predictor -> final activity prediction

  Usage:
    # a file of new molecules (CSV/XLSX with a 'smiles' column)
    python predict.py RESULTS/CHEMBL220_AChE new_molecules.csv

    # a single SMILES on the command line
    python predict.py RESULTS/CHEMBL220_AChE --smiles "CCOc1ccccc1"

    # custom smiles column / output path
    python predict.py RESULTS/CHEMBL220_AChE new.csv --smiles-col SMILES --out preds.xlsx

  Output columns: SMILES, Predicted, Chemprop_Pred, Within_AD
    Within_AD = True means the molecule is inside the model's applicability
    domain (trust the prediction more); False = extrapolation, treat with care.
=============================================================================
"""
import os
import sys
import argparse
import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd

# reuse the exact same feature computation as training
import qsar_pipeline as qp
from autogluon.tabular import TabularPredictor


def load_new_smiles(args):
    if args.smiles:
        return pd.DataFrame({args.smiles_col: [args.smiles]})
    path = args.input
    if not os.path.exists(path):
        sys.exit(f"Input file not found: {path}")
    df = pd.read_excel(path) if path.lower().endswith((".xlsx", ".xls")) else pd.read_csv(path)
    df.columns = [c.strip() for c in df.columns]
    if args.smiles_col not in df.columns:
        sys.exit(f"Column '{args.smiles_col}' not in {path}. Have: {list(df.columns)}")
    return df


def chemprop_predict(ckpt_path, smiles_list, batch_size=128):
    """Run the saved Chemprop final model on new SMILES."""
    import torch
    from lightning import pytorch as pl
    from chemprop import data, featurizers, models

    mpnn = models.MPNN.load_from_checkpoint(ckpt_path)
    feat = featurizers.SimpleMoleculeMolGraphFeaturizer()
    pts = [data.MoleculeDatapoint.from_smi(s, np.array([0.0])) for s in smiles_list]
    dset = data.MoleculeDataset(pts, feat)
    loader = data.build_dataloader(dset, batch_size=batch_size, shuffle=False)
    trainer = pl.Trainer(accelerator="auto", devices=1, logger=False,
                         enable_progress_bar=False, enable_checkpointing=False)
    with torch.inference_mode():
        preds = trainer.predict(mpnn, loader)
    return np.concatenate([p.numpy().ravel() for p in preds])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("target_dir", help="RESULTS/<target> folder produced by the pipeline")
    ap.add_argument("input", nargs="?", default=None, help="CSV/XLSX of new molecules")
    ap.add_argument("--smiles", default=None, help="predict a single SMILES string")
    ap.add_argument("--smiles-col", default="smiles")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    tdir = args.target_dir.rstrip("/")
    model_dir = os.path.join(tdir, "chosen_model")
    feats_csv = os.path.join(tdir, "selected_features.csv")
    ckpt = os.path.join(tdir, "_cache", "chemprop_final.ckpt")
    fit_csv = os.path.join(tdir, "Data", "fit.csv")

    for p in (model_dir, feats_csv, fit_csv):
        if not os.path.exists(p):
            sys.exit(f"Missing required artifact: {p}\nRe-run the pipeline for this target first.")
    if not os.path.exists(ckpt):
        sys.exit(f"Missing Chemprop checkpoint: {ckpt}\n"
                 f"Delete '{os.path.join(tdir, '_cache')}' and re-run this target to regenerate it.")

    final_features = pd.read_csv(feats_csv)["Feature"].tolist()
    desc_features = [f for f in final_features if f != "chemprop_pred"]

    new_df = load_new_smiles(args)
    smiles = new_df[args.smiles_col].astype(str).tolist()
    print(f"Predicting {len(smiles)} molecule(s) with model in {tdir} ...")

    # 1. tabular features (same functions as training)
    rows = [qp.compute_features(s) for s in smiles]
    valid = [i for i, r in enumerate(rows) if r is not None]
    if not valid:
        sys.exit("None of the SMILES could be parsed by RDKit.")
    feat_df = pd.DataFrame([rows[i] for i in valid]).replace([np.inf, -np.inf], np.nan)
    feat_df = feat_df.reindex(columns=desc_features).apply(pd.to_numeric, errors="coerce").fillna(0)
    valid_smiles = [smiles[i] for i in valid]

    # 2. chemprop feature
    print("  running Chemprop ...")
    feat_df["chemprop_pred"] = chemprop_predict(ckpt, valid_smiles)

    # 3. AutoGluon prediction
    print("  running AutoGluon ...")
    predictor = TabularPredictor.load(model_dir)
    X = feat_df.reindex(columns=final_features).fillna(0)
    y_pred = predictor.predict(X).values

    # 4. applicability domain (same z-score rule as training, from fit.csv)
    fit = pd.read_csv(fit_csv)
    tmean = fit[final_features].mean(0).values
    tstd = fit[final_features].std(0).values + 1e-8
    z = np.abs((X[final_features].values - tmean) / tstd).mean(1)
    within_ad = z <= 3.0

    out = pd.DataFrame({
        "SMILES": valid_smiles,
        "Predicted": y_pred,
        "Chemprop_Pred": feat_df["chemprop_pred"].values,
        "Within_AD": within_ad,
    })
    out_path = args.out or os.path.join(tdir, "new_predictions.xlsx")
    out.to_excel(out_path, index=False)
    print(f"\nSaved: {out_path}")
    print(out.to_string(index=False))


if __name__ == "__main__":
    main()
