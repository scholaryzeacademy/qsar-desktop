"""
Automated receptor-structure picker for onboarding a new docking target.

Given a gene symbol, finds a real human UniProt accession (UniProt REST),
then the best-resolution PDB entry for that accession that has a bound
small-molecule ligand (RCSB Search API + Data API), and picks the ligand
entity most likely to be the real inhibitor (largest formula weight, after
excluding crystallization additives/ions — the same kind of exclusion
docking/receptor_prep.py already applies post-hoc).

This does NOT decide 'validated' — it only proposes (pdb_id, resname) pairs
for scripts/validate_target.py to actually prepare + redock + RMSD-check.
A proposal that fails redocking is simply not validated; nothing here is
trusted until the real geometry check downstream passes.

Usage:
    python scripts/select_receptor.py EGFR
    python scripts/select_receptor.py EGFR --uniprot P00533   # skip lookup
"""
import argparse
import json
import sys
import time
import urllib.request
import urllib.parse

UNIPROT_URL = "https://rest.uniprot.org/uniprotkb/search"
UNIPROT_ENTRY_URL = "https://rest.uniprot.org/uniprotkb/{}.json"
RCSB_ENTRY_URL = "https://data.rcsb.org/rest/v1/core/entry/{}"
RCSB_NONPOLY_URL = "https://data.rcsb.org/rest/v1/core/nonpolymer_entity/{}/{}"

# additives/ions/cryoprotectants that are never the real inhibitor, even
# though they show up as HETATM groups — extends receptor_prep.py's list
# with a few more common ones seen across PDB depositions.
ADDITIVE_BLACKLIST = {
    "HOH", "WAT", "SO4", "PO4", "GOL", "EDO", "PEG", "ACT", "NA", "CL", "K",
    "MG", "ZN", "CA", "MN", "DMS", "TRS", "FMT", "IOD", "PG4", "1PE", "P6G",
    "BME", "MPD", "IPA", "EOH", "TAR", "CIT", "BOG", "LDA", "OLA", "MYR",
    "PLM", "PLP", "FAD", "FMN", "NAD", "NAP", "NDP", "GDP", "GTP", "ADP",
    "ATP", "AMP", "SAH", "SAM", "HEM", "HEC", "COA", "UNL", "UNX", "UNK",
    "SIN", "MES", "HEPES", "IMD", "NH4", "CO", "NI", "CD", "CU", "FE",
    "FE2", "BR", "F", "GSH", "SCN", "AZI", "PGE", "PG5", "PG6", "1PG", "15P",
    "2PE", "7PE", "PGO", "MRD", "PEG", "SR", "CS", "RB", "LI", "BA", "CO3",
    "NO3", "OXL", "ACY", "PGA",
    # N-/O-linked glycosylation sugars — extremely common on secreted/membrane
    # receptor ectodomains (e.g. ERBB2), never the actual inhibitor of interest.
    "NAG", "NDG", "BMA", "MAN", "FUC", "GAL", "GLC", "SIA", "BGC", "A2G",
    "NGA", "XYP", "FUL", "RAM",
    # non-hydrolyzable ATP/GTP analogs used as crystallization cofactor mimics
    # (nucleotide-binding-site occupants, not drug-like inhibitors) — common on
    # kinases/GTPases (e.g. RAF1/RAS complexes).
    "GNP", "ANP", "AGS", "ACP", "GSP", "G2P", "GCP", "APC", "ADX", "AN2",
}


def _get_json(url, retries=3, delay=1.0):
    for i in range(retries):
        try:
            with urllib.request.urlopen(url, timeout=20) as r:
                return json.load(r)
        except Exception:
            if i == retries - 1:
                raise
            time.sleep(delay)



def find_uniprot(gene_symbol, organism_id=9606):
    q = f"(gene:{gene_symbol}) AND (organism_id:{organism_id}) AND (reviewed:true)"
    url = f"{UNIPROT_URL}?query={urllib.parse.quote(q)}&fields=accession,gene_names,protein_name&format=json&size=5"
    d = _get_json(url)
    results = d.get("results", [])
    if not results:
        # retry without reviewed filter (TrEMBL fallback for less-studied targets)
        q = f"(gene:{gene_symbol}) AND (organism_id:{organism_id})"
        url = f"{UNIPROT_URL}?query={urllib.parse.quote(q)}&fields=accession,gene_names,protein_name&format=json&size=5"
        d = _get_json(url)
        results = d.get("results", [])
    if not results:
        return None
    r0 = results[0]
    return r0["primaryAccession"]


def candidate_pdb_ids(uniprot_acc, max_resolution=3.5, rows=30):
    """UniProt's own cross-reference list (PDB database) already carries
       method + resolution + chain range per structure — simpler and more
       reliable than guessing RCSB Search API attribute paths for the
       UniProt->entry join, which vary by schema version."""
    d = _get_json(UNIPROT_ENTRY_URL.format(uniprot_acc))
    refs = d.get("uniProtKBCrossReferences", [])
    scored = []
    for ref in refs:
        if ref.get("database") != "PDB":
            continue
        pdb_id = ref.get("id")
        props = {p["key"]: p["value"] for p in ref.get("properties", [])}
        method = props.get("Method", "")
        res_str = props.get("Resolution", "")
        try:
            res = float(res_str.split()[0])
        except (ValueError, IndexError):
            res = None
        if "X-ray" not in method:
            continue
        if res is None or res > max_resolution:
            continue
        scored.append((res, pdb_id))
    scored.sort(key=lambda t: t[0])
    return [pdb_id for _, pdb_id in scored[:rows]]


def best_ligand_for_entry(pdb_id):
    """Returns (resname, formula_weight) for the largest non-additive bound
       ligand in this entry, or None if there isn't one."""
    entry = _get_json(RCSB_ENTRY_URL.format(pdb_id))
    ids = entry.get("rcsb_entry_container_identifiers", {}).get("non_polymer_entity_ids") or []
    best = None
    for eid in ids:
        try:
            ne = _get_json(RCSB_NONPOLY_URL.format(pdb_id, eid))
        except Exception:
            continue
        comp_id = (ne.get("pdbx_entity_nonpoly") or {}).get("comp_id")
        fw_kda = ((ne.get("rcsb_nonpolymer_entity") or {}).get("formula_weight"))
        if not comp_id or comp_id.upper() in ADDITIVE_BLACKLIST:
            continue
        fw = (fw_kda or 0) * 1000.0   # RCSB reports formula_weight in kDa
        if fw < 180:   # below this it's almost always a cryoprotectant/buffer, not a real inhibitor
            continue
        if best is None or fw > best[1]:
            best = (comp_id, fw)
    return best


def pick(gene_symbol, uniprot_acc=None, max_candidates=8):
    acc = uniprot_acc or find_uniprot(gene_symbol)
    if not acc:
        return {"gene": gene_symbol, "error": "no UniProt accession found"}
    pdb_ids = candidate_pdb_ids(acc)
    if not pdb_ids:
        return {"gene": gene_symbol, "uniprot": acc, "error": "no liganded PDB entries found"}
    for pdb_id in pdb_ids[:max_candidates]:
        try:
            lig = best_ligand_for_entry(pdb_id)
        except Exception as e:
            continue
        if lig:
            return {"gene": gene_symbol, "uniprot": acc, "pdb_id": pdb_id,
                     "resname": lig[0], "ligand_formula_weight": lig[1]}
    return {"gene": gene_symbol, "uniprot": acc, "error": f"no usable ligand in top {max_candidates} candidates",
            "tried": pdb_ids[:max_candidates]}


def pick_candidates(gene_symbol, uniprot_acc=None, max_candidates=15):
    """Like pick(), but returns an ORDERED list of every (pdb_id, resname)
       option found (best resolution first), so a caller can fall through to
       the next one if the top choice fails receptor prep / redocking."""
    acc = uniprot_acc or find_uniprot(gene_symbol)
    if not acc:
        return []
    pdb_ids = candidate_pdb_ids(acc)
    out = []
    for pdb_id in pdb_ids[:max_candidates]:
        try:
            lig = best_ligand_for_entry(pdb_id)
        except Exception:
            continue
        if lig:
            out.append({"pdb_id": pdb_id, "resname": lig[0], "ligand_formula_weight": lig[1]})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("gene_symbol")
    ap.add_argument("--uniprot", default=None, help="skip UniProt lookup, use this accession directly")
    args = ap.parse_args()
    result = pick(args.gene_symbol, uniprot_acc=args.uniprot)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
