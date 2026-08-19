# Docking module

Structure-based docking: **Vina → PoseBusters validity gate → pose
consensus (self-consistency + optional GNINA CNN second opinion) → PLIP
(or a built-in distance-based fallback) interaction diagram**. AutoDock4
has been removed (GPL; GNINA is now the independent second opinion — see
`engines.py`). The Docking tab activates automatically once Vina is on
PATH and at least one target has a validated profile in
`docking_registry.json`.

## Files
| File | Role |
|---|---|
| `availability.py` | detects which tools/binaries are present |
| `ligand_prep.py` | SMILES -> 3D conformer -> PDBQT (RDKit + Meeko) |
| `validity.py` | PoseBusters physical-validity gate |
| `rmsd.py` | atom-map-safe RMSD (refuses to compare non-identical molecules) |
| `consensus.py` | pose selection + confidence (validity + self-consistency + GNINA) |
| `engines.py` | `VinaEngine` (docking) + `GninaRescorer` (optional CNN second opinion) |
| `profile.py` | registry load/save; resolves receptor paths portably (see below) |
| `receptor_prep.py` | one-time receptor prep: extract ligand, strip, repair (PDBFixer), PDBQT |
| `pipeline.py` | `dock_compound` (per-compound) + `redock_reference` (per-target validation) |
| `interactions.py` | built-in distance-based interaction detector (fallback) |
| `interaction_diagram.py` | PLIP detection (if installed) + LigPlot-style 2D diagram renderer |

## Registry path portability
`docking_registry.json` stores receptor filenames as **basenames**
(`receptor.pdbqt`, `receptor_clean.pdb`), resolved at load time relative to
`DOCKING_TARGETS_DIR/<target_id>/` (default `./docking_targets`). Earlier
versions of this file stored absolute paths baked in at prep time, which
broke the moment the project folder moved — `profile.load_profile()` still
accepts a legacy absolute path if it happens to still exist, but always
prefers the portable resolution.

## Validating a new target before trusting it
1. `receptor_prep.prepare_receptor(...)` — extracts the co-crystal ligand,
   strips to protein-only, repairs (PDBFixer), builds the grid box, writes
   the receptor PDBQT, and appends a profile to the registry with
   `"validated": false`.
2. `pipeline.redock_reference(...)` — re-docks the same reference ligand and
   computes RMSD to its crystal pose. **< ~2 Å** is the trust threshold.
3. Run an enrichment test (actives + decoys) — AUC / EF@20%.
4. Only flip `"validated": true` (and record `reference_rmsd` /
   `enrichment_auc` / `enrichment_ef20`) once both pass — see `scripts/` for
   the one-off scripts used to validate the `cox2` target already in this
   registry. The UI shows a VALIDATED/UNVALIDATED badge with the real
   numbers; never trust a docking score for an unvalidated target.

## Design notes (do not "fix" these)
- PoseBusters is a **gate**, not a scoring engine: poses are filtered before
  ranking, not ranked by validity.
- `rmsd.safe_rmsd` **refuses** to compare poses that aren't the same
  molecule (checked via the heavy-atom graph) — this prevents silent
  atom-mapping corruption that would otherwise wreck the consensus/
  confidence signal.
- Without GNINA, confidence is capped at `medium` (no second opinion) — see
  `consensus.assign_confidence`. This is intentional, not a missing feature.
