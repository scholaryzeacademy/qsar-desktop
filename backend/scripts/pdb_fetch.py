"""
Shared PDB-entry fetcher. RCSB no longer serves a legacy .pdb file for many
newer/larger depositions (mmCIF-only) — a plain files.rcsb.org/download/x.pdb
404s for those even though the structure exists. Fall back to fetching the
mmCIF and converting it with gemmi (already a project dependency), so a
receptor candidate isn't skipped just because it's a recent deposition.
"""
import os
import shutil
import urllib.request

import gemmi

FETCH_TIMEOUT = 30   # seconds — urlretrieve has NO timeout param of its own (only
                      # urlopen does), so an RCSB connection that stalls after accepting
                      # the socket (not a DNS/refused-connection failure, which fail fast
                      # regardless) hangs indefinitely instead of surfacing an error.


def _download(url, out_path):
    with urllib.request.urlopen(url, timeout=FETCH_TIMEOUT) as r, open(out_path, "wb") as f:
        shutil.copyfileobj(r, f)


def fetch_pdb(pdb_id, out_path):
    """Writes a legacy-format PDB file to out_path, converting from mmCIF if
       RCSB has no legacy .pdb for this entry."""
    try:
        _download(f"https://files.rcsb.org/download/{pdb_id}.pdb", out_path)
        return out_path
    except urllib.error.HTTPError as e:
        if e.code != 404:
            raise
    cif_path = out_path + ".cif"
    _download(f"https://files.rcsb.org/download/{pdb_id}.cif", cif_path)
    structure = gemmi.read_structure(cif_path)
    structure.setup_entities()
    structure.write_pdb(out_path)
    os.remove(cif_path)
    return out_path
