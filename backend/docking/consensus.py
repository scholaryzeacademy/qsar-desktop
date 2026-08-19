"""
Pose selection + confidence (Vina + GNINA).  [TESTED logic]

AutoDock4 cross-engine consensus was removed. Confidence for a single-docker
(Vina) pipeline is now built from three independent signals:
  1. PoseBusters validity   — is the pose physically possible at all?
  2. pose self-consistency  — do Vina's own top poses cluster (reproducible mode)?
  3. GNINA CNNscore         — does a CNN think the pose is a real binding pose?

  high   : self-consistent AND CNNscore >= 0.5
  medium : one positive signal (self-consistent OR CNNscore >= 0.5)
  low    : valid pose but neither
  none   : no physically valid pose
When GNINA is unavailable, confidence is capped at 'medium' (no second opinion).
"""
from .rmsd import safe_rmsd

CNN_GOOD = 0.5


def select_pose(vina_poses, gate, threshold=2.0):
    """PoseBusters-gate Vina poses, pick the best valid one, measure self-consistency."""
    valid, reports = gate.filter(vina_poses) if vina_poses else ([], [])
    result = {"threshold_A": threshold, "n_valid": len(valid), "validity_reports": reports}
    if not valid:
        result.update(consensus_pose=None, best=None, pose_self_consistency=0,
                      reason="no physically valid poses")
        return result
    best = min(valid, key=lambda p: p.score)
    near = 0
    for p in valid:
        if p is best:
            continue
        try:
            if safe_rmsd(best.mol, p.mol) <= threshold:
                near += 1
        except ValueError:
            pass
    result.update(vina_score=round(best.score, 2),
                  consensus_pose={"engine": best.engine, "score": round(best.score, 2), "pose_id": best.pose_id},
                  best=best, pose_self_consistency=near,
                  reason="best physically valid Vina pose")
    return result


def assign_confidence(result, gnina=None):
    """Combine validity + self-consistency + GNINA CNNscore into a confidence tier."""
    if not result.get("consensus_pose"):
        return "none"
    consistent = result.get("pose_self_consistency", 0) >= 1
    cnn = (gnina or {}).get("cnn_score")
    good_cnn = cnn is not None and cnn >= CNN_GOOD
    if gnina is None or cnn is None:
        return "medium" if consistent else "low"      # no second opinion -> cap at medium
    if consistent and good_cnn:
        return "high"
    if consistent or good_cnn:
        return "medium"
    return "low"