"""
Per-compound docking orchestration + per-target validation.
[orchestration WRITTEN; gated helpers TESTED; subprocess runs UNVALIDATED]

  dock_compound:
    ligand prep -> Vina dock -> PoseBusters gate -> best valid pose
                -> GNINA CNN rescore (second opinion)
                -> confidence (validity + self-consistency + CNNscore)
                -> optional 2D interaction diagram + reference-residue overlap
  redock_reference: re-dock the target's known ligand, RMSD to the crystal pose.
"""
import os
from rdkit import Chem

from .ligand_prep import prepare_ligand
from .validity import ValidityGate
from .consensus import select_pose, assign_confidence
from .engines import VinaEngine, GninaRescorer
from .rmsd import safe_rmsd


def pose_pdb_with_hydrogens(pose_mol):
    """PDB block of the docked pose for 3D (ball-and-stick) display, with every
       hydrogen present — including polar ones like NH2/OH.

       VinaEngine.dock() hands back heavy-atom-only poses (Chem.RemoveHs, since
       that's what the interaction detector/GNINA rescoring already validated
       against), so there is no docked H position to reuse here. Chem.AddHs(...,
       addCoords=True) fills every hydrogen back in with standard bond geometry
       from the docked heavy-atom positions — the same approach visualization
       tools (PyMOL/Chimera 'add hydrogens') use on a heavy-atom structure.
       This is a geometry completion for display, not Vina's own optimised H
       placement — polar-H orientation here is a reasonable estimate, not the
       exact rotamer Vina searched."""
    vis_mol = Chem.AddHs(pose_mol, addCoords=True)
    return Chem.MolToPDBBlock(vis_mol)


def dock_compound(profile, smiles, engine=None, rescorer=None, n_poses=9,
                  rmsd_threshold=2.0, make_diagram=False, reference_interactions=None):
    lig = prepare_ligand(smiles)
    if not lig.ok:
        return {"smiles": smiles, "status": "ligand_prep_failed", "error": lig.error}
    engine = engine or VinaEngine()
    errors = {}
    try:
        vina_poses = engine.dock(profile, lig, n_poses=n_poses) if engine.available() else []
    except Exception as e:
        vina_poses = []; errors["vina"] = str(e)

    gate = ValidityGate(receptor_pdb=profile.get("receptor_pdb"))
    sel = select_pose(vina_poses, gate, rmsd_threshold)

    result = {"smiles": smiles, "target": profile.get("target_id"),
              "n_valid": sel["n_valid"], "pose_self_consistency": sel.get("pose_self_consistency", 0),
              "vina_score": sel.get("vina_score"), "consensus_pose": sel.get("consensus_pose"),
              "engine_errors": errors, "reason": sel["reason"]}

    best = sel.get("best")
    gnina = None
    if best is not None:
        # GNINA CNN rescoring (second opinion)
        rescorer = rescorer or GninaRescorer()
        if rescorer.available() and profile.get("receptor_pdb"):
            gnina = rescorer.rescore(profile["receptor_pdb"], best.mol)
            result["gnina"] = gnina
        # interaction profiling + optional 2D diagram: PLIP (gold-standard
        # typing) when installed, else the built-in distance-based detector;
        # rendered LigPlot+-style (H-bond/pi-stacking/hydrophobic/salt-bridge/
        # halogen, polar/non-polar residue halos, legend — see CLAUDE.md §8).
        if profile.get("receptor_pdb") and os.path.exists(profile["receptor_pdb"]):
            try:
                from . import interaction_diagram as ID
                from . import interactions as I
                inter, source = ID.detect_interactions(profile["receptor_pdb"], best.mol)
                result["interactions"] = inter
                result["interaction_source"] = source
                if reference_interactions is not None:
                    result["residue_overlap_pct"] = I.residue_overlap(inter, reference_interactions)
                if make_diagram:
                    ref_res = {h["residue"] for h in (reference_interactions or [])}
                    result["interaction_png"] = ID.diagram_png(
                        best.mol, inter, title=f"{smiles[:30]}", source=source, ref_residues=ref_res)
            except Exception as e:
                result["interaction_error"] = str(e)
        if make_diagram:
            try:
                result["pose_pdb"] = pose_pdb_with_hydrogens(best.mol)
            except Exception as e:
                result["pose_pdb_error"] = str(e)

    result["confidence"] = assign_confidence(sel, gnina)
    result["status"] = "ok" if sel.get("consensus_pose") else "no_pose"
    return result


def redock_reference(profile, reference_smiles, crystal_sdf=None, engine=None, rmsd_threshold=2.0):
    """VALIDATION: re-dock the reference ligand; if a crystal SDF is given, compute
       RMSD of the top pose to the crystal pose (atom-map-safe)."""
    engine = engine or VinaEngine()
    if not engine.available():
        return {"status": "engine_unavailable", "engine": engine.name}
    lig = prepare_ligand(reference_smiles)
    if not lig.ok:
        return {"status": "ligand_prep_failed", "error": lig.error}
    poses = engine.dock(profile, lig, n_poses=10)
    if not poses:
        return {"status": "no_pose"}
    top = min(poses, key=lambda p: p.score)
    out = {"status": "ok", "engine": engine.name, "top_score": round(top.score, 2), "n_poses": len(poses)}
    if crystal_sdf and os.path.exists(crystal_sdf):
        crystal = next((m for m in Chem.SDMolSupplier(crystal_sdf, removeHs=True) if m), None)
        if crystal is not None:
            try:
                out["reference_rmsd"] = round(safe_rmsd(top.mol, crystal), 3)
                out["validated"] = out["reference_rmsd"] < rmsd_threshold
            except ValueError as e:
                out["rmsd_error"] = str(e)
    return out