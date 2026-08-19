"""
PhytoScreen docking module (SCAFFOLD).

Status of each piece:
  availability.py  [TESTED]    tool/package detection
  ligand_prep.py   [TESTED]    SMILES -> 3D -> PDBQT (RDKit + Meeko)
  validity.py      [TESTED]    PoseBusters physical-validity gate
  rmsd.py          [TESTED]    atom-map-safe cross-engine RMSD
  consensus.py     [TESTED]    validity-gated consensus + confidence
  engines.py       [SCAFFOLD]  Vina / AutoDock4 subprocess wrappers  (need binaries)
  receptor_prep.py [SCAFFOLD]  PDB -> clean -> box -> PDBQT           (need PDBFixer/prepare_receptor/fpocket)
  pipeline.py      [SCAFFOLD]  per-compound orchestration + reference redock validation
  profile.py       [TESTED]    docking target profile (JSON) load/save

  The [SCAFFOLD] parts call external docking binaries that were NOT available
  in development, so they are written but UNVALIDATED. Validate them on a known
  complex (e.g. re-dock a co-crystallised ligand and confirm RMSD < 2 A) before
  trusting any result.
"""