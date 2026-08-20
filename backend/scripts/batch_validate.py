"""
Batch-onboard docking receptors for every usable QSAR target in models/.

For each target: resolve a gene symbol -> try candidate (PDB id, ligand
resname) pairs in order, auto-detect which chain actually carries that
reference ligand (see detect_chain.py), and run scripts/validate_target.py
as an isolated subprocess (so one target's crash or a stuck Vina run can't
take the whole batch down). Moves to the next candidate PDB if one fails;
a target that runs out of candidates is logged as unresolved, never given
a fabricated 'validated' entry.

Candidates come from TWO sources, merged (CSV first, deduped by pdb_id):
  1. scripts/panel_candidates.py — pre-vetted structural-quality ranking
     from panel_results_v2.csv (resolution/RSCC/RSR), much richer pools
     than live search for the same gene.
  2. scripts/select_receptor.py — live UniProt/RCSB lookup, current-state
     fallback for genes the CSV snapshot doesn't cover (or covers thinly).
If nothing in that merged list validates, a deeper CSV tier is tried
(panel_candidates' extra_limit, beyond its cheap top-5) before giving up.

By default this RE-VALIDATES every target, including ones already
"validated": true — the CSV's crystallographic ranking can disagree with
what we previously found (see panel_candidates.py's PDGFRB example), so a
plain resolution/RSCC-based ranking is never enough on its own; only a real
Vina redocking (validate_target.py) decides. To avoid a CSV-driven re-pick
silently swapping a well-validated receptor for a worse-but-still-passing
one, an existing validated entry is only overwritten by a new validated
result whose reference_rmsd is <= the prior one (see _accept_or_revert);
otherwise the prior entry is restored and the next candidate is tried.
Pass --skip-validated to restore the old fast-skip behavior for targets
already validated (useful for incremental runs once this snapshot is
already reconciled).

Usage:
    python scripts/batch_validate.py                      # all usable targets
    python scripts/batch_validate.py CHEMBL203_EGFR ...    # just these
    python scripts/batch_validate.py --skip-validated      # skip already-validated
"""
import copy
import json
import os
import sys
import subprocess

_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_SCRIPTS_DIR))

from scripts import select_receptor
from scripts import panel_candidates
from scripts.detect_chain import chain_for_ligand
from scripts.pdb_fetch import fetch_pdb
from docking.profile import REGISTRY

DEEP_EXTRA_LIMIT = 10  # extra panel-CSV candidates beyond top-5, tried only if everything else fails

MODELS_DIR = os.environ.get("TARGETS_DIR", "models")  # same env var + default
                          # as serving/model_adapter.py's TARGETS_DIR — must
                          # match, since this drives which targets recommend.py
                          # considers "usable" (has a real QSAR model); a
                          # hardcoded "models" here would silently disagree
                          # with a custom TARGETS_DIR override (see
                          # BUILD_WINDOWS.md's "local override paths").
LOG_PATH = os.path.join(_SCRIPTS_DIR, "batch_validate_log.jsonl")   # own dir,
                          # NOT cwd-relative — an audit log, not shared data,
                          # and this module is called from app.py with the
                          # server's cwd (repo root), not scripts/'s own dir
PER_TARGET_TIMEOUT = 45 * 60  # seconds; enrichment docks 16 compounds, generous margin

# folder-name suffix -> gene symbol override, for names that aren't a clean
# single HGNC symbol (multi-subunit complexes / family assays).
GENE_OVERRIDES = {
    "CDK4_CyclinD1": "CDK4",
    "HDAC_family": "HDAC6",
    "ITGA2B_ITGB3": "ITGA2B",
    "p53_MDM2": "MDM2",
    "AChE": "ACHE",  # panel_results_v2.csv's targetSymbol is uppercase HGNC form
}


def usable_targets():
    out = []
    for tid in sorted(os.listdir(MODELS_DIR)):
        bdir = os.path.join(MODELS_DIR, tid)
        if not os.path.isdir(bdir) or not tid.startswith("CHEMBL"):
            continue
        needed = ["chosen_model", "selected_features.csv", os.path.join("Data", "fit.csv")]
        if all(os.path.exists(os.path.join(bdir, n)) for n in needed):
            out.append(tid)
    return out


def gene_for_target(target_id):
    suffix = target_id.split("_", 1)[1] if "_" in target_id else target_id
    return GENE_OVERRIDES.get(suffix, suffix)


def already_validated(target_id):
    entry = registry_entry(target_id)
    return bool(entry and entry.get("validated"))


def registry_entry(target_id):
    if not os.path.exists(REGISTRY):
        return None
    reg = json.load(open(REGISTRY))
    return next((t for t in reg.get("targets", []) if t["target_id"] == target_id), None)


def _write_registry_entry(target_id, entry):
    """Overwrite target_id's dict in the registry with `entry` in place —
       used to revert a CSV-driven re-pick that turned out worse than what
       was already there (see _accept_or_revert)."""
    from docking.profile import registry_lock, write_registry_json
    with registry_lock():   # see registry_lock's docstring — needed once multiple targets validate concurrently
        reg = json.load(open(REGISTRY))
        for i, t in enumerate(reg["targets"]):
            if t["target_id"] == target_id:
                reg["targets"][i] = entry
                break
        write_registry_json(reg)


def _restore_receptor_files(target_id, entry):
    """Rebuilds receptor_clean.pdb/receptor.pdbqt/protein_raw.pdb from
       entry's own pdb_source (already on disk — fetch_pdb names raw PDBs
       per-pdb_id, e.g. '4RT7_raw.pdb', so a LATER candidate's fetch never
       overwrites an EARLIER one's) + chain.

       Why this exists: validate_target.py's receptor-prep step writes
       directly into docking_targets/<target_id>/{protein_raw,receptor_clean,
       receptor.pdbqt} — filenames shared across every candidate for that
       target, not per-pdb_id. _accept_or_revert() reverting the REGISTRY
       entry back to prior_entry does NOT undo that: a real batch run left
       3 already-validated targets (CHEMBL1974_FLT3, CHEMBL2742_FGFR3,
       CHEMBL333_MMP2) with a registry entry correctly pointing at their
       accepted structure while the receptor FILES on disk were actually
       built from a later, ultimately-rejected candidate — box center off
       by 90-130 A from the receptor actually being docked against, so
       every live docking run against them was silently searching empty
       space. This restores the files to match what the registry (still)
       claims, every time a revert happens, so that state can't recur.

       entry['chain'] may be None for registry entries written before this
       field existed — falls back to chain=None (keeps every chain; the
       box math is unaffected since it's derived from the reference
       ligand's own coordinates, not the chain filter) rather than skip
       the repair outright."""
    from docking import receptor_prep as RP
    pdb_source = entry.get("pdb_source")
    if not pdb_source:
        print(f"[{target_id}] WARNING: prior entry has no pdb_source — cannot restore receptor files")
        return False
    raw_pdb = os.path.join("docking_targets", target_id, pdb_source)
    if not os.path.exists(raw_pdb):
        print(f"[{target_id}] WARNING: {raw_pdb} missing on disk — cannot restore receptor files "
              f"for the reverted entry; live docking against this target may be using STALE files "
              f"from a rejected candidate until this is repaired manually.")
        return False
    try:
        RP.build_receptor(raw_pdb, target_id, ref_resname=entry.get("reference_ligand_resname"),
                          chain=entry.get("chain"), out_dir="docking_targets")
        print(f"[{target_id}] receptor files restored to match the reverted entry ({pdb_source})")
        return True
    except Exception as e:
        print(f"[{target_id}] WARNING: failed to restore receptor files after revert: {e}")
        return False


def _accept_or_revert(target_id, prior_entry):
    """After validate_target.py has already written its result into the
       registry: decide whether to keep it or restore prior_entry.

       No prior validated entry -> keep whatever came back (nothing to
       protect). Prior validated entry -> only keep the new one if it's
       ALSO validated and its reference_rmsd is no worse than before;
       otherwise put prior_entry back AND rebuild the receptor files to
       match it (see _restore_receptor_files) and report this candidate as
       rejected, so a plain crystallographic re-ranking can never silently
       downgrade a receptor that already passed real Vina redocking — in
       either the registry OR the files actually used to dock against it.

       Returns (accepted: bool, entry: dict) — entry is whatever the
       registry now holds for target_id."""
    new_entry = registry_entry(target_id)
    if not prior_entry or not prior_entry.get("validated"):
        return bool(new_entry and new_entry.get("validated")), new_entry

    prior_rmsd = prior_entry.get("reference_rmsd")
    new_validated = bool(new_entry and new_entry.get("validated"))
    new_rmsd = new_entry.get("reference_rmsd") if new_entry else None
    improved_or_equal = new_validated and prior_rmsd is not None and new_rmsd is not None \
        and new_rmsd <= prior_rmsd
    if improved_or_equal:
        return True, new_entry
    _write_registry_entry(target_id, prior_entry)
    _restore_receptor_files(target_id, prior_entry)
    return False, prior_entry


def log(entry):
    with open(LOG_PATH, "a") as f:
        f.write(json.dumps(entry) + "\n")


def merged_candidates(gene):
    """panel_candidates.py's cheap (top-5) tier first, then any
       select_receptor.py live candidates not already covered — CSV-ranked
       first, deduped by pdb_id. Each candidate is tagged with where it
       came from (source: 'version2_csv' | 'live_rcsb', + csv_rank when
       known) so the batch log can trace every pick back to the Version 2
       CSV evidence, not just report a bare pdb_id."""
    panel = panel_candidates.candidates_from_panel(gene)
    for c in panel:
        c["source"] = "version2_csv"
    try:
        live = select_receptor.pick_candidates(gene)
    except Exception:
        live = []
    for c in live:
        c["source"] = "live_rcsb"
        c.setdefault("csv_rank", None)
    seen, out = set(), []
    for c in panel + live:
        if c["pdb_id"] not in seen:
            seen.add(c["pdb_id"])
            out.append(c)
    return out


def _try_candidate(target_id, prior_entry, pdb_id, resname, source=None, csv_rank=None):
    """Fetch + chain-detect + run validate_target.py for one candidate.
       Returns 'accepted' | 'rejected' | 'skipped' (chain-detect/fetch
       failure, no subprocess run).

       source/csv_rank trace this candidate back to where it came from
       (Version 2 CSV rank, vs. a live RCSB lookup) — carried into every
       log() entry below so scripts/batch_validate_log.jsonl records that
       provenance, not just a bare pdb_id."""
    prov = {"source": source, "csv_rank": csv_rank}
    tmp_dir = os.environ.get("TMPDIR", "/tmp")
    tmp_pdb = os.path.join(tmp_dir, f"{target_id}_{pdb_id}_probe.pdb")
    try:
        fetch_pdb(pdb_id, tmp_pdb)
        chain = chain_for_ligand(tmp_pdb, resname)
    except Exception as e:
        print(f"[{target_id}] {pdb_id}/{resname}: chain-detect failed ({e}), skipping candidate")
        log({"target_id": target_id, "pdb_id": pdb_id, "resname": resname,
             "status": "skipped", "reason": f"chain-detect failed: {e}", **prov})
        return "skipped"
    finally:
        if os.path.exists(tmp_pdb):
            os.remove(tmp_pdb)
    if chain is None:
        print(f"[{target_id}] {pdb_id}/{resname}: ligand not found in any chain, skipping candidate")
        log({"target_id": target_id, "pdb_id": pdb_id, "resname": resname,
             "status": "skipped", "reason": "ligand not found in any chain", **prov})
        return "skipped"

    print(f"[{target_id}] trying {pdb_id} / {resname} / chain {chain} (source={source}, csv_rank={csv_rank}) ...")
    # Absolute script path (subprocess.run resolves a relative one against the
    # CALLER's cwd, not this file's own directory — that's the repo root when
    # invoked from app.py, not backend/scripts/). cwd is deliberately left as
    # the parent's own (unset here -> inherited) so validate_target.py's own
    # cwd-relative models/docking_registry.json/docking_targets resolution
    # still lands on the repo root, same as everywhere else in the app.
    cmd = [sys.executable, os.path.join(_SCRIPTS_DIR, "validate_target.py"), target_id, pdb_id, resname, "--chain", chain]
    # NOTE: validate_target.py's receptor-prep step (docking/receptor_prep.py
    # prepare_receptor) overwrites the registry entry for target_id with a
    # bare, unvalidated profile as soon as it runs — BEFORE redocking or
    # enrichment even start, and regardless of whether the run ultimately
    # succeeds. So _accept_or_revert must run on every exit path below once
    # the subprocess has actually been launched (it may have already
    # clobbered a good prior entry even on a timeout/crash), not just on
    # the success path — this is what a real run caught: a target that had
    # been validated lost its validated entry to a later *failed* candidate
    # until this was fixed.
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=PER_TARGET_TIMEOUT)
    except subprocess.TimeoutExpired:
        print(f"[{target_id}] {pdb_id}: TIMED OUT after {PER_TARGET_TIMEOUT}s")
        _accept_or_revert(target_id, prior_entry)
        log({"target_id": target_id, "pdb_id": pdb_id, "resname": resname, "chain": chain,
             "status": "timeout", **prov})
        return "skipped"

    tail = "\n".join((proc.stdout + proc.stderr).splitlines()[-15:])
    if proc.returncode != 0:
        print(f"[{target_id}] {pdb_id}: FAILED (exit {proc.returncode})\n{tail}")
        _accept_or_revert(target_id, prior_entry)
        log({"target_id": target_id, "pdb_id": pdb_id, "resname": resname, "chain": chain,
             "status": "error", "tail": tail, **prov})
        return "skipped"

    accepted, entry = _accept_or_revert(target_id, prior_entry)
    print(f"[{target_id}] {pdb_id}: done, accepted={accepted}, "
          f"rmsd={entry.get('reference_rmsd') if entry else None}")
    log({"target_id": target_id, "pdb_id": pdb_id, "resname": resname, "chain": chain,
         "status": "accepted" if accepted else ("reverted" if prior_entry and prior_entry.get("validated")
                                                  else "not_validated"),
         "reference_rmsd": entry.get("reference_rmsd") if entry else None,
         "enrichment_auc": entry.get("enrichment_auc") if entry else None, **prov})
    return "accepted" if accepted else "rejected"


def run_one(target_id, skip_validated=False):
    if skip_validated and already_validated(target_id):
        print(f"[{target_id}] already validated, skipping")
        return
    gene = gene_for_target(target_id)
    print(f"[{target_id}] gene={gene}")
    prior_entry = copy.deepcopy(registry_entry(target_id))

    tried = set()

    first_tier = merged_candidates(gene)
    if not first_tier:
        print(f"[{target_id}] no receptor candidates found for gene '{gene}'")
        log({"target_id": target_id, "gene": gene, "status": "no_candidates"})

    for cand in first_tier:
        tried.add(cand["pdb_id"])
        if _try_candidate(target_id, prior_entry, cand["pdb_id"], cand["resname"],
                           source=cand.get("source"), csv_rank=cand.get("csv_rank")) == "accepted":
            return

    # nothing in the cheap tier worked (or there was nothing) — only now pay
    # for the deeper panel-CSV tier (live RCSB lookups beyond top-5)
    deep_tier = panel_candidates.candidates_from_panel(gene, extra_limit=DEEP_EXTRA_LIMIT, exclude=tried)
    for cand in deep_tier:
        if cand["pdb_id"] in tried:
            continue
        tried.add(cand["pdb_id"])
        if _try_candidate(target_id, prior_entry, cand["pdb_id"], cand["resname"],
                           source="version2_csv", csv_rank=cand.get("csv_rank")) == "accepted":
            return

    print(f"[{target_id}] exhausted all candidates without an accepted validated receptor")


def main():
    args = sys.argv[1:]
    skip_validated = "--skip-validated" in args
    args = [a for a in args if a != "--skip-validated"]
    targets = args or usable_targets()
    print(f"{len(targets)} target(s) to process (skip_validated={skip_validated})")
    for i, tid in enumerate(targets, 1):
        print(f"\n=== [{i}/{len(targets)}] {tid} ===")
        try:
            run_one(tid, skip_validated=skip_validated)
        except Exception as e:
            print(f"[{tid}] unexpected batch-level error: {e}")
            log({"target_id": tid, "status": "batch_error", "error": str(e)})


if __name__ == "__main__":
    main()
