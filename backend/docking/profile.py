"""Docking target profiles (per-target receptor + box + reference).  [TESTED: load/save/box]"""
import contextlib
import os, json
import numpy as np

REGISTRY = os.environ.get("DOCKING_REGISTRY", "docking_registry.json")
DOCKING_TARGETS_DIR = os.environ.get("DOCKING_TARGETS_DIR", "docking_targets")


@contextlib.contextmanager
def registry_lock():
    """Cross-PROCESS advisory lock (fcntl.flock on a sibling .lock file)
       guarding one full read-modify-write cycle against docking_registry.json.

       Every write site does its own json.load(REGISTRY) -> mutate -> json.dump
       — fine for a single writer, but as soon as more than one process can be
       validating DIFFERENT targets at the same time (see scripts/
       batch_validate.py's parallel runner), two of these read-then-write
       cycles can interleave: A reads, B reads (before A's write), A writes,
       B writes — B's write is from a now-stale copy and silently discards
       A's update. flock blocks a second process at the 'read' step until the
       first process's 'write' has completed, so every read-modify-write
       cycle is atomic with respect to every other process using this same
       lock — not just this one file's own writes.

       fcntl.flock is process-scoped, not thread-scoped: two threads in the
       SAME process both get the lock immediately (harmless here — every
       call site in this codebase does its registry I/O synchronously on
       one thread per logical operation, never two threads racing the same
       write inside one process)."""
    import fcntl
    lock_path = REGISTRY + ".lock"
    with open(lock_path, "w") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def grid_box_from_ligand(coords, padding=8.0, min_size=20.0):
    """Center + size (A) of the search box from reference-ligand heavy-atom coords."""
    c = np.asarray(coords, float)
    center = c.mean(axis=0)
    size = (c.max(axis=0) - c.min(axis=0)) + 2 * padding
    size = np.maximum(size, min_size)
    return [round(float(x), 3) for x in center], [round(float(x), 3) for x in size]


def load_registry():
    if not os.path.exists(REGISTRY):
        return {}
    with open(REGISTRY) as f:
        data = json.load(f)
    items = data.get("targets", data if isinstance(data, list) else [])
    return {t["target_id"]: t for t in items}


def _resolve_receptor_path(target_id, filename_or_path):
    """Resolve a receptor file portably. Registries may store either just a
       basename (portable, preferred going forward) or a legacy absolute
       path from wherever the profile was first built — that absolute path
       breaks the moment the project folder moves or is packaged onto a
       different machine (e.g. a Windows .exe), so it's only trusted if it
       still exists; otherwise we fall back to DOCKING_TARGETS_DIR/<target_id>/<basename>."""
    if filename_or_path and os.path.isabs(filename_or_path) and os.path.exists(filename_or_path):
        return filename_or_path
    base = os.path.basename(filename_or_path) if filename_or_path else None
    if base:
        cand = os.path.join(DOCKING_TARGETS_DIR, target_id, base)
        if os.path.exists(cand):
            return cand
    return filename_or_path  # let the caller's own existence checks fail loudly and clearly


def load_profile(target_id):
    reg = load_registry()
    if target_id not in reg:
        raise KeyError(f"no docking profile for '{target_id}'")
    p = dict(reg[target_id])
    p["receptor_pdbqt"] = _resolve_receptor_path(target_id, p.get("receptor_pdbqt"))
    p["receptor_pdb"] = _resolve_receptor_path(target_id, p.get("receptor_pdb"))
    return p


def save_registry(profiles):
    write_registry_json({"targets": list(profiles.values())})


def write_registry_json(reg_dict):
    """json.dump straight into REGISTRY truncates it first, so a reader
       (e.g. the live app answering a docking request) racing a writer can
       see a half-written/truncated file and crash on json.load — a real
       risk once multiple targets validate concurrently while the app stays
       up for testing. Writing to a same-directory temp file and os.replace-
       ing it over REGISTRY is atomic on POSIX: any concurrent reader sees
       either the complete old file or the complete new one, never a partial
       write. Callers still need registry_lock() around their own read-
       modify-write cycle to avoid losing another WRITER's update — this
       only protects readers from ever seeing corruption."""
    tmp_path = f"{REGISTRY}.tmp.{os.getpid()}"
    with open(tmp_path, "w") as f:
        json.dump(reg_dict, f, indent=2)
    os.replace(tmp_path, REGISTRY)