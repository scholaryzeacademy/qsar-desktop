# Docking module (SCAFFOLD)

Structure-based docking: **Vina + AutoDock4 → PoseBusters validity gate →
atom-map-safe consensus**. The Docking tab activates automatically once the
tools are installed and at least one target profile exists.

## What is validated vs scaffold
| Piece | File | Status |
|---|---|---|
| Tool detection | availability.py | tested |
| Ligand prep (SMILES→3D→PDBQT) | ligand_prep.py | tested (RDKit+Meeko) |
| PoseBusters validity gate | validity.py | tested |
| Atom-map-safe RMSD | rmsd.py | tested (the anti-corruption fix) |
| Consensus + confidence | consensus.py | tested (logic, mock poses) |
| Profile store + grid box | profile.py | tested |
| Vina / AutoDock4 engines | engines.py | **scaffold** (need binaries) |
| Receptor prep | receptor_prep.py | **scaffold** (need pdbfixer/meeko/fpocket) |
| Orchestration + redock | pipeline.py | **scaffold** (needs engines) |

## To enable
1. `pip install posebusters meeko gemmi` ; install Vina + AutoDock4/AutoGrid4 on PATH.
2. Implement the scaffolded steps in `receptor_prep.py` and `AutoDock4Engine.dock`
   (Vina is written; AD4 parsing is stubbed).
3. Build a `docking_registry.json` of prepared targets (see profile.py).
4. **Validate before trusting:** re-dock each target's co-crystallised ligand and
   confirm RMSD < ~2 Å (redock_reference). Do not ship a target that fails this.

## Design notes (do not "fix" these)
- PoseBusters is a **gate**, not a third engine: each engine's poses are filtered
  before comparison.
- Cross-engine RMSD uses `rmsd.safe_rmsd`, which **refuses** to compare poses that
  aren't the same molecule — this prevents the silent atom-mapping corruption that
  otherwise destroys the consensus signal.
- Vina+AD4 consensus is a **pose-agreement confidence** signal, not a scoring
  upgrade; real ranking lift comes from ML rescoring (future).