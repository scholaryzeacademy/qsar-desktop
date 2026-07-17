"""
Protein-ligand interaction analysis + 2D interaction diagram.  [TESTED locally]

Detects the residues a docked pose contacts (distance-based H-bond / hydrophobic /
aromatic rules) and renders a 2D report figure: the ligand drawn in 2D with the
interacting residues annotated around it, coloured by interaction type.

Dependency-light on purpose: RDKit + matplotlib + Biopython only (no MDAnalysis /
PLIP / PyMOL), so it runs anywhere the rest of PhytoScreen runs and is redistributable.
"""
import io, base64
import numpy as np
from rdkit import Chem
from rdkit.Chem import Draw, AllChem
from rdkit.Chem.Draw import rdMolDraw2D

# distance cutoffs (Angstrom)
HBOND_MAX = 3.6
HYDROPHOBIC_MAX = 4.2
AROMATIC_MAX = 5.5
_POLAR = {"N", "O"}


def _protein_atoms(receptor_pdb):
    """Return list of (resname, resid, chain, element, coord) for protein atoms."""
    from Bio.PDB import PDBParser
    s = PDBParser(QUIET=True).get_structure("r", receptor_pdb)
    atoms = []
    for model in s:
        for ch in model:
            for res in ch:
                if res.id[0] != " ":          # standard residues only
                    continue
                for a in res.get_atoms():
                    el = a.element.strip() or a.get_name()[0]
                    atoms.append((res.resname.strip(), res.id[1], ch.id, el, np.array(a.coord, float)))
        break
    return atoms


def detect_interactions(pose_mol, receptor_pdb):
    """Return a de-duplicated list of interacting residues with interaction type."""
    conf = pose_mol.GetConformer()
    lig = [(pose_mol.GetAtomWithIdx(i).GetSymbol(),
            np.array(conf.GetAtomPosition(i), float)) for i in range(pose_mol.GetNumAtoms())]
    prot = _protein_atoms(receptor_pdb)
    hits = {}
    for rn, rid, ch, pel, pc in prot:
        key = f"{rn}{rid}"
        for lsym, lc in lig:
            d = float(np.linalg.norm(lc - pc))
            typ = None
            if lsym in _POLAR and pel in _POLAR and d <= HBOND_MAX:
                typ = "hbond"
            elif lsym == "C" and pel == "C" and d <= HYDROPHOBIC_MAX:
                typ = "hydrophobic"
            if typ:
                prev = hits.get(key)
                # keep the closest / prioritise hbond over hydrophobic
                rank = {"hbond": 2, "hydrophobic": 1}
                if prev is None or rank[typ] > rank[prev["type"]] or d < prev["distance"]:
                    hits[key] = {"residue": key, "resname": rn, "resid": rid, "chain": ch,
                                 "type": typ, "distance": round(d, 2)}
    return sorted(hits.values(), key=lambda h: (h["type"] != "hbond", h["distance"]))


def residue_overlap(query_interactions, reference_interactions):
    """% of the reference ligand's residues that the query also contacts."""
    ref = {h["residue"] for h in reference_interactions}
    if not ref:
        return None
    q = {h["residue"] for h in query_interactions}
    return round(100 * len(ref & q) / len(ref), 1)


_COLORS = {"hbond": "#0d9488", "hydrophobic": "#d97706", "aromatic": "#7c3aed"}


def interaction_diagram_png(pose_mol, interactions, title="", ref_residues=None):
    """Render a 2D report figure: ligand structure + interacting residues + legend.
       Returns a base64 PNG string (embeddable as data:image/png;base64,...)."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D

    # 2D depiction of the ligand
    flat = Chem.Mol(pose_mol)
    try:
        Chem.RemoveStereochemistry(flat)
        AllChem.Compute2DCoords(flat)
    except Exception:
        pass
    d = rdMolDraw2D.MolDraw2DCairo(360, 360)
    d.DrawMolecule(flat)
    d.FinishDrawing()
    png = d.GetDrawingText()
    import PIL.Image as Image
    lig_img = Image.open(io.BytesIO(png))

    fig, (axL, axR) = plt.subplots(1, 2, figsize=(9, 4.6), gridspec_kw={"width_ratios": [1, 1]})
    axL.imshow(lig_img); axL.axis("off"); axL.set_title(title or "Docked ligand", fontsize=11)

    axR.axis("off")
    axR.set_title("Interacting residues", fontsize=11, loc="left")
    y = 0.95
    if not interactions:
        axR.text(0.02, y, "No close contacts detected.", fontsize=10, color="#64748b")
    for h in interactions[:16]:
        c = _COLORS.get(h["type"], "#64748b")
        shared = ref_residues and h["residue"] in ref_residues
        label = f"{h['residue']}  ({h['type']}, {h['distance']} Å)" + ("  ★ shared with reference" if shared else "")
        axR.plot([0.02, 0.06], [y, y], color=c, lw=3, transform=axR.transAxes)
        axR.text(0.09, y, label, fontsize=9.5, va="center",
                 fontweight="bold" if shared else "normal", transform=axR.transAxes)
        y -= 0.058
    legend = [Line2D([0], [0], color=_COLORS["hbond"], lw=3, label="H-bond"),
              Line2D([0], [0], color=_COLORS["hydrophobic"], lw=3, label="Hydrophobic")]
    axR.legend(handles=legend, loc="lower left", fontsize=8, frameon=False)

    buf = io.BytesIO()
    fig.tight_layout(); fig.savefig(buf, format="png", dpi=120); plt.close(fig)
    return base64.b64encode(buf.getvalue()).decode()