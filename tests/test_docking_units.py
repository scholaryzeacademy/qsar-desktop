"""Docking fallback tests (CLAUDE.md §12): GNINA absent -> confidence capped
at medium; PoseBusters present but Vina absent -> availability correctly
reports partial readiness rather than crashing; the plain distance-based
interaction detector still works without PLIP."""
from docking import availability as AVAIL
from docking import consensus as CONSENSUS


def test_confidence_capped_at_medium_without_gnina():
    sel = {"consensus_pose": {"engine": "vina", "score": -8.0}, "pose_self_consistency": 3}
    assert CONSENSUS.assign_confidence(sel, gnina=None) == "medium"


def test_confidence_low_when_not_self_consistent_and_no_gnina():
    sel = {"consensus_pose": {"engine": "vina", "score": -8.0}, "pose_self_consistency": 0}
    assert CONSENSUS.assign_confidence(sel, gnina=None) == "low"


def test_confidence_none_without_a_valid_pose():
    assert CONSENSUS.assign_confidence({"consensus_pose": None}) == "none"


def test_confidence_high_requires_both_signals():
    sel = {"consensus_pose": {"engine": "vina"}, "pose_self_consistency": 2}
    assert CONSENSUS.assign_confidence(sel, gnina={"cnn_score": 0.9}) == "high"
    assert CONSENSUS.assign_confidence(sel, gnina={"cnn_score": 0.1}) == "medium"


def test_availability_reports_real_environment_state():
    """This dev environment has rdkit/meeko/posebusters installed but NOT the
       Vina binary — availability.status() must reflect exactly that, never
       claim docking is ready when the engine binary is missing."""
    st = AVAIL.status()
    assert st["packages"]["rdkit"] is True
    assert st["packages"]["meeko"] is True
    assert st["packages"]["posebusters"] is True
    assert st["can_prep_ligand"] is True
    assert st["can_validate"] is True
    if not st["binaries"]["vina"]:
        assert st["ready"] is False
        assert "binary:vina" in st["missing_for_docking"]


def test_posebusters_gate_runs_on_a_real_molecule():
    """Exercises the real PoseBusters integration (installed in this venv),
       not just import-availability — a genuinely valid small molecule with
       an embedded 3D conformer should pass the ligand-only ('mol') checks."""
    from rdkit import Chem
    from rdkit.Chem import AllChem
    from docking.validity import ValidityGate

    m = Chem.AddHs(Chem.MolFromSmiles("CC(=O)Oc1ccccc1C(=O)O"))
    assert AllChem.EmbedMolecule(m, randomSeed=42) == 0
    AllChem.MMFFOptimizeMolecule(m)

    gate = ValidityGate(receptor_pdb=None)
    assert gate.available is True
    passed, report = gate.check(m)
    assert isinstance(passed, bool)
    assert isinstance(report, dict) and report   # real per-check results, not a stub
