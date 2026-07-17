"""
============================================================
  REPORTING  (reporting.py)
============================================================
  Two report layers, both decision-oriented for a chemist:

  (1) BUILD-TIME report  -> build_report(report_data, out_dir)
      Generated once per target from the held-out TEST set (where
      true pIC50 is known). Covers ALL six candidate models so a
      chemist can compare, with the shipped model highlighted:
        - model comparison: test R2 / RMSE / Spearman / top-pick
        - validation-vs-test R2 (overfitting check)
        - per-model actual-vs-predicted (test), coloured by AD
        - per-model conformal coverage (predicted +/- interval vs actual)
        - residual distribution
      Saves PNGs + report.json (raw numbers, so a web UI can redraw).

  (2) PREDICT-TIME report -> prediction_report(in_dom, out_dom, asset, model, out_dir)
      Generated per query batch. NO ground truth exists here, so it
      shows predictions + CONFIDENCE, never accuracy:
        - ranked potency with conformal interval error bars
        - applicability-domain map (how far each molecule is from training)
        - confidence tier (green/amber/red) per molecule
      Saves PNGs + a prediction_report.json.
============================================================
"""

import os
import json
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

PLOT = dict(dpi=120, figsize=(6.2, 4.4))
C_IN, C_OUT, C_BEST, C_OTHER = "#2c7fb8", "#d95f0e", "#2ca25f", "#9ecae1"


def _save(fig, path):
    fig.tight_layout(); fig.savefig(path); plt.close(fig)


def _confidence_tier(width, in_ad, conf_label):
    """Plain-language confidence from interval width + domain membership."""
    if not in_ad:
        return "red"            # outside training chemistry
    if width <= 1.5:
        return "green"
    if width <= 3.0:
        return "amber"
    return "red"


# ============================================================
#   BUILD-TIME REPORT
# ============================================================
def build_report(report_data, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    rd = report_data
    best = rd["best_name"]
    yt = np.array(rd["test_actual"])
    in_ad = np.array(rd["in_ad"], dtype=bool)
    names = list(rd["metrics_by_model"].keys())
    mbm = rd["metrics_by_model"]
    paths = {}

    # --- 1. model comparison bars (test R2, Spearman, top-pick, RMSE) ---
    fig, axs = plt.subplots(2, 2, figsize=(9, 6.5), dpi=PLOT["dpi"])
    metrics_plot = [("test_r2", "Test R²"), ("spearman", "Spearman ρ (ranking)"),
                    ("top_pick_pct", "Top-pick percentile"), ("test_rmse", "Test RMSE (lower=better)")]
    for ax, (key, title) in zip(axs.ravel(), metrics_plot):
        vals = [mbm[n][key] for n in names]
        colors = [C_BEST if n == best else C_OTHER for n in names]
        ax.barh(range(len(names)), vals, color=colors)
        ax.set_yticks(range(len(names))); ax.set_yticklabels(names, fontsize=8)
        ax.invert_yaxis(); ax.set_title(title, fontsize=10)
        ax.grid(axis="x", alpha=.3)
    fig.suptitle(f"{rd['name']} — model comparison (shipped: {best})", fontsize=11)
    p = os.path.join(out_dir, "report_model_comparison.png"); _save(fig, p); paths["model_comparison"] = p

    # --- 2. validation vs test R2 (overfitting gap) ---
    fig, ax = plt.subplots(figsize=PLOT["figsize"], dpi=PLOT["dpi"])
    x = np.arange(len(names)); w = .38
    ax.bar(x - w/2, [mbm[n]["val_r2"] for n in names], w, label="validation R²", color=C_OTHER)
    ax.bar(x + w/2, [mbm[n]["test_r2"] for n in names], w, label="test R²", color=C_IN)
    ax.set_xticks(x); ax.set_xticklabels(names, rotation=30, ha="right", fontsize=8)
    ax.axhline(0, color="k", lw=.6); ax.legend(fontsize=8)
    ax.set_title("Validation vs test R² (large gap = overfit)", fontsize=10)
    p = os.path.join(out_dir, "report_val_vs_test.png"); _save(fig, p); paths["val_vs_test"] = p

    # --- 3. per-model actual vs predicted + conformal coverage ---
    for name in names:
        m = rd["models"][name]
        yp = np.array(m["test_pred"]); pil = np.array(m["pi_low"]); pih = np.array(m["pi_high"])
        safe = name.replace(" ", "_").replace("(", "").replace(")", "")
        lo, hi = float(min(yt.min(), yp.min())), float(max(yt.max(), yp.max()))

        fig, ax = plt.subplots(figsize=PLOT["figsize"], dpi=PLOT["dpi"])
        ax.scatter(yt[in_ad], yp[in_ad], s=26, alpha=.7, color=C_IN, edgecolors="white", label="in-domain")
        if (~in_ad).any():
            ax.scatter(yt[~in_ad], yp[~in_ad], s=26, alpha=.7, color=C_OUT, edgecolors="white", label="out-of-domain")
        ax.plot([lo, hi], [lo, hi], "r--", lw=1.4)
        tag = "  [SHIPPED]" if name == best else ""
        ax.set_xlabel("Actual pIC50"); ax.set_ylabel("Predicted pIC50")
        ax.set_title(f"{name}{tag} — R²={mbm[name]['test_r2']}  RMSE={mbm[name]['test_rmse']}", fontsize=10)
        ax.legend(fontsize=8)
        p = os.path.join(out_dir, f"report_avp_{safe}.png"); _save(fig, p); paths[f"avp_{safe}"] = p

        # conformal coverage: compounds sorted by actual, predicted with interval band
        order = np.argsort(yt)
        fig, ax = plt.subplots(figsize=PLOT["figsize"], dpi=PLOT["dpi"])
        xs = np.arange(len(yt))
        ax.fill_between(xs, pil[order], pih[order], color=C_OTHER, alpha=.35, label=f"{int(rd['confidence']*100)}% interval")
        ax.plot(xs, yt[order], "o", ms=3, color="k", label="actual")
        inside = np.mean((yt >= pil) & (yt <= pih))
        ax.set_title(f"{name}{tag} — interval coverage {inside:.0%} (target {rd['confidence']:.0%})", fontsize=10)
        ax.set_xlabel("compound (sorted by actual)"); ax.set_ylabel("pIC50"); ax.legend(fontsize=8)
        p = os.path.join(out_dir, f"report_coverage_{safe}.png"); _save(fig, p); paths[f"coverage_{safe}"] = p

    # --- 4. residuals of the shipped model ---
    yp_best = np.array(rd["models"][best]["test_pred"])
    fig, ax = plt.subplots(figsize=PLOT["figsize"], dpi=PLOT["dpi"])
    ax.hist((yt - yp_best), bins=20, color=C_IN, alpha=.8)
    ax.axvline(0, color="r", lw=1.2)
    ax.set_title(f"Residuals — shipped model ({best})", fontsize=10)
    ax.set_xlabel("actual − predicted (pIC50)"); ax.set_ylabel("count")
    p = os.path.join(out_dir, "report_residuals.png"); _save(fig, p); paths["residuals"] = p

    # --- raw numbers for a web UI to redraw interactively ---
    rd_out = dict(rd); rd_out["plot_paths"] = {k: v.replace("\\", "/") for k, v in paths.items()}
    with open(os.path.join(out_dir, "report.json"), "w") as f:
        json.dump(rd_out, f, indent=2)
    return paths


# ============================================================
#   PREDICT-TIME REPORT
# ============================================================
def prediction_report(in_dom, out_dom, asset, model_name, out_dir, top_k=20):
    os.makedirs(out_dir, exist_ok=True)
    ep = asset["endpoint"]
    conf = asset.get("conformal_by_model", {}).get(model_name) or asset.get("conformal")
    lvl = int(round(conf["confidence"] * 100)) if conf else 90
    lower_col = f"Lower_{lvl}"
    paths = {}

    top = in_dom.head(top_k).iloc[::-1]   # best at top of the chart
    if len(top):
        pred = top[f"Predicted_{ep}"].to_numpy()
        pil = top["PI_low"].to_numpy() if "PI_low" in top else pred
        pih = top["PI_high"].to_numpy() if "PI_high" in top else pred
        width = pih - pil
        tiers = [_confidence_tier(w, True, lvl) for w in width]
        cmap = {"green": "#2ca25f", "amber": "#f0a202", "red": "#d95f0e"}
        colors = [cmap[t] for t in tiers]

        # 1. ranked potency with interval error bars
        fig, ax = plt.subplots(figsize=(7, max(3, 0.32 * len(top))), dpi=PLOT["dpi"])
        ys = np.arange(len(top))
        ax.errorbar(pred, ys, xerr=[pred - pil, pih - pred], fmt="o", ecolor="#bbbbbb",
                    elinewidth=2, capsize=3, color="#333333", zorder=3)
        ax.scatter(pred, ys, c=colors, s=60, zorder=4, edgecolors="white")
        labels = [s if len(s) <= 30 else s[:27] + "…" for s in top["Standardised_SMILES"]]
        ax.set_yticks(ys); ax.set_yticklabels(labels, fontsize=7, family="monospace")
        ax.set_xlabel(f"Predicted {ep}  (dot) with {lvl}% interval (bar)")
        ax.set_title(f"Top {len(top)} candidates — {model_name}\n"
                     f"green=high confidence, amber=medium, red=wide/uncertain", fontsize=10)
        ax.grid(axis="x", alpha=.3)
        p = os.path.join(out_dir, "predict_ranked.png"); _save(fig, p); paths["ranked"] = p

    # 2. applicability-domain map (all scored molecules)
    allr = pd.concat([in_dom, out_dom], ignore_index=True)
    if "AD_distance" in allr and len(allr):
        d = allr["AD_distance"].dropna().to_numpy()
        fig, ax = plt.subplots(figsize=PLOT["figsize"], dpi=PLOT["dpi"])
        ax.hist(d, bins=30, color=C_IN, alpha=.8)
        ax.axvline(asset["ad_threshold"], color="r", lw=1.6, label="domain boundary")
        ax.set_xlabel("distance from training chemistry (0=identical, 1=unrelated)")
        ax.set_ylabel("molecules"); ax.legend(fontsize=8)
        ax.set_title(f"Applicability domain — {int(np.mean(d <= asset['ad_threshold'])*100)}% inside", fontsize=10)
        p = os.path.join(out_dir, "predict_ad_map.png"); _save(fig, p); paths["ad_map"] = p

    # add a plain-language confidence column to the shortlist and save
    if len(in_dom) and "PI_low" in in_dom:
        w = (in_dom["PI_high"] - in_dom["PI_low"]).to_numpy()
        in_dom = in_dom.copy()
        in_dom["Confidence"] = [_confidence_tier(wi, True, lvl) for wi in w]
    out_csv = os.path.join(out_dir, "prediction_ranked.csv")
    pd.concat([in_dom, out_dom], ignore_index=True).to_csv(out_csv, index=False)

    summary = {
        "target": asset["name"], "model": model_name, "confidence": conf["confidence"] if conf else None,
        "n_in_domain": int(len(in_dom)), "n_out_domain": int(len(out_dom)),
        "plot_paths": {k: v.replace("\\", "/") for k, v in paths.items()},
        "ranked_csv": out_csv.replace("\\", "/"),
    }
    with open(os.path.join(out_dir, "prediction_report.json"), "w") as f:
        json.dump(summary, f, indent=2)
    return paths, summary