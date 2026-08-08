"""
LigPlot+/Discovery-Studio-style 2D interaction diagram.  [renderer TESTED; PLIP detection = validate-on-your-machine]

Detection:
  * If PLIP is installed, use it for ACCURATE interaction typing — H-bond,
    pi-pi stacking (parallel/T-shaped), hydrophobic (Alkyl/Pi-Alkyl), pi-cation,
    salt bridge, halogen bond — on the real protein-ligand complex, with real
    atom-level names (never invented: every (ligand_atom, protein_atom) pair
    traces to an actual PLIP-detected contact). PLIP is the gold standard here.
  * Otherwise fall back to the built-in distance-based detector, which only
    distinguishes H-bond/hydrophobic and has no atom-level identity — its
    entries are labelled "(distance-based)" so the table never implies a
    precision it doesn't have.

Rendering (follows the universal 2D-diagram / BIOVIA-Discovery-Studio conventions):
  * Central ligand drawn flat (RDKit 2D depiction).
  * Green DASHED lines        -> conventional hydrogen bonds.
  * Dark pink SOLID/DASHED     -> pi-pi stacking (stacked / T-shaped).
  * Light-pink DOTTED          -> Alkyl / Pi-Alkyl hydrophobic contacts.
  * Orange SOLID/DASHED        -> pi-cation / salt bridge (electrostatic).
  * Cyan DASHED                -> halogen bonds.
  * Residues labelled 3-letter + number (e.g. LEU144, GLY219), placed around
    the ligand, with polar (purple) / non-polar (green) colouring.
  * Legend included.
NOTE: this is a schematic in that style, not a pixel-identical LigPlot+/
Discovery Studio clone (exact swatch hex values are not reproduced from a
licensed reference — the category/type vocabulary and general colour families
are what's matched).
"""
import io, os, base64, math, tempfile, subprocess
import numpy as np
from rdkit import Chem
from rdkit.Chem import AllChem
from rdkit.Chem.Draw import rdMolDraw2D

# residue polarity for halo colouring
_POLAR_RES = {"ARG","LYS","ASP","GLU","GLN","ASN","HIS","SER","THR","TYR","CYS","TRP"}

# real aromatic ring atom names per residue (PDB atom naming) — used to tell a
# genuine Pi-Alkyl contact (protein atom is actually part of the aromatic ring)
# from a plain Alkyl one, instead of guessing from residue name alone.
_AROMATIC_RING_ATOMS = {
    "PHE": {"CG", "CD1", "CD2", "CE1", "CE2", "CZ"},
    "TYR": {"CG", "CD1", "CD2", "CE1", "CE2", "CZ"},
    "TRP": {"CG", "CD1", "CD2", "NE1", "CE2", "CE3", "CZ2", "CZ3", "CH2"},
    "HIS": {"CG", "ND1", "CD2", "CE1", "NE2"},
}

_CATEGORY = {"hbond": "Hydrogen Bond", "pistack_p": "Pi-Pi Stacking", "pistack_t": "Pi-Pi Stacking",
             "alkyl": "Hydrophobic", "pialkyl": "Hydrophobic", "pication": "Electrostatic",
             "saltbridge": "Electrostatic", "halogen": "Halogen", "hydrophobic": "Hydrophobic"}

_STYLE = {"hbond":      {"color": "#2e7d32", "ls": (0,(4,3)), "lw": 1.8, "label": "Conventional Hydrogen Bond"},
          "pistack_p":  {"color": "#c2185b", "ls": "solid",   "lw": 2.0, "label": "Pi-Pi Stacked"},
          "pistack_t":  {"color": "#c2185b", "ls": (0,(4,3)), "lw": 2.0, "label": "Pi-Pi T-shaped"},
          "alkyl":      {"color": "#d9a8cf", "ls": (0,(1,2)), "lw": 1.3, "label": "Alkyl"},
          "pialkyl":    {"color": "#d9a8cf", "ls": (0,(1,2)), "lw": 1.9, "label": "Pi-Alkyl"},
          "pication":   {"color": "#f57c00", "ls": "solid",   "lw": 2.0, "label": "Pi-Cation"},
          "saltbridge": {"color": "#f57c00", "ls": (0,(5,2)), "lw": 2.0, "label": "Salt Bridge"},
          "halogen":    {"color": "#00acc1", "ls": (0,(4,3)), "lw": 1.8, "label": "Halogen Bond"},
          "hydrophobic":{"color": "#8a8a8a", "ls": (0,(1,2)), "lw": 1.3, "label": "Hydrophobic Contact (distance-based)"}}


def _atom_name(plip_atom):
    """Real PDB atom name (e.g. 'CD1', 'O1') for a PLIP-wrapped atom, via OpenBabel's
       residue atom ID — never fabricated, falls back to '?' only if unreadable."""
    try:
        return plip_atom.OBAtom.GetResidue().GetAtomID(plip_atom.OBAtom).strip()
    except Exception:
        return "?"


def _hydrophobic_type(restype, protein_atom_name):
    """Alkyl vs Pi-Alkyl: Pi-Alkyl only if the contacting protein atom is a real
       member of that residue's aromatic ring (checked by actual atom name, not
       just 'residue happens to be aromatic somewhere')."""
    return "pialkyl" if protein_atom_name in _AROMATIC_RING_ATOMS.get(restype, ()) else "alkyl"


# ---------- detection ----------
def plip_available():
    try:
        import plip  # noqa
        return True
    except Exception:
        from shutil import which
        return which("plip") is not None


def detect_with_plip(receptor_pdb, pose_mol):
    """Run PLIP on the receptor+pose complex; return unified interaction dicts.
       Returns None if PLIP can't run (caller falls back)."""
    try:
        # write a complex PDB: receptor + ligand (as HETATM 'LIG')
        with tempfile.TemporaryDirectory() as td:
            complex_pdb = os.path.join(td, "complex.pdb")
            # drop the receptor's own END/ENDMDL record: appending ligand atoms
            # after it would put them past the point most PDB parsers (PLIP
            # included) stop reading, so the ligand never gets seen.
            rec_lines = [l for l in open(receptor_pdb).read().rstrip().splitlines()
                         if not l.startswith(("END", "ENDMDL"))]
            rec = "\n".join(rec_lines)
            lig_pdb = Chem.MolToPDBBlock(pose_mol)
            lig_lines = []
            for l in lig_pdb.splitlines():
                if l.startswith(("HETATM", "ATOM")):
                    lig_lines.append("HETATM" + l[6:17] + "LIG A 999" + l[26:])
            open(complex_pdb, "w").write(rec + "\n" + "\n".join(lig_lines) + "\nEND\n")

            from plip.structure.preparation import PDBComplex
            mol = PDBComplex(); mol.load_pdb(complex_pdb); mol.analyze()
            site = list(mol.interaction_sets.values())[0]
            out = []

            def emit(typ, residue, distance, ligand_atom=None, protein_atom=None):
                label = _STYLE[typ]["label"]
                if ligand_atom and protein_atom:
                    name = f"LIG:{ligand_atom} — {residue}:{protein_atom}"
                else:
                    name = f"LIG — {residue}"
                out.append({"residue": residue, "type": typ, "category": _CATEGORY[typ], "label": label,
                            "distance": round(distance, 2), "ligand_atom": ligand_atom,
                            "protein_atom": protein_atom, "name": name})

            for h in site.hbonds_ldon + site.hbonds_pdon:
                residue = f"{h.restype}{h.resnr}"
                prot_atom, lig_atom = (h.d, h.a) if h.protisdon else (h.a, h.d)
                emit("hbond", residue, h.distance_ad, _atom_name(lig_atom), _atom_name(prot_atom))
            for p in site.pistacking:
                residue = f"{p.restype}{p.resnr}"
                emit("pistack_p" if p.type == "P" else "pistack_t", residue, p.distance)
            for hc in site.hydrophobic_contacts:
                residue = f"{hc.restype}{hc.resnr}"
                prot_name = _atom_name(hc.bsatom)
                emit(_hydrophobic_type(hc.restype, prot_name), residue, hc.distance,
                     _atom_name(hc.ligatom), prot_name)
            for pc in getattr(site, "pication_laro", []) + getattr(site, "pication_paro", []):
                emit("pication", f"{pc.restype}{pc.resnr}", pc.distance)
            for sb in site.saltbridge_lneg + site.saltbridge_pneg:
                emit("saltbridge", f"{sb.restype}{sb.resnr}", sb.distance)
            for hal in getattr(site, "halogen_bonds", []):
                emit("halogen", f"{hal.restype}{hal.resnr}", hal.distance,
                     _atom_name(hal.don.x), _atom_name(hal.acc.o))
            return out
    except Exception:
        return None


def _dedupe_for_diagram(interactions):
    """The full interaction list can have several atom-level contacts to the
       same residue (real — a residue often makes multiple contacts); the ring
       schematic needs one bubble per residue, so keep only the closest contact
       per (residue, type) for rendering. The table (full list) is unaffected."""
    best = {}
    for h in interactions:
        k = (h["residue"], h["type"])
        if k not in best or h["distance"] < best[k]["distance"]:
            best[k] = h
    return list(best.values())


def detect_interactions(receptor_pdb, pose_mol):
    """PLIP if available, else the built-in distance-based detector. Returns the
       FULL (non-deduplicated) interaction list — one entry per real detected
       contact — suitable for both the diagram (deduped internally) and a
       nonbonding-interactions table."""
    if plip_available():
        res = detect_with_plip(receptor_pdb, pose_mol)
        if res is not None:
            return res, "PLIP"
    try:
        from .interactions import detect_interactions as _dist
    except Exception:
        from interactions import detect_interactions as _dist
    fallback = _dist(pose_mol, receptor_pdb)
    for h in fallback:
        h["category"] = _CATEGORY[h["type"]]
        h["label"] = _STYLE[h["type"]]["label"]
        h["ligand_atom"] = None
        h["protein_atom"] = None
        h["name"] = f"LIG — {h['residue']} (distance-based, no atom-level detail)"
    return fallback, "distance-based"


# ---------- rendering (LigPlot+ style) ----------
def diagram_png(pose_mol, interactions, title="", source="", ref_residues=None):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D
    import PIL.Image as Image

    # flat ligand image
    flat = Chem.Mol(pose_mol)
    try:
        Chem.RemoveStereochemistry(flat); AllChem.Compute2DCoords(flat)
    except Exception:
        pass
    d = rdMolDraw2D.MolDraw2DCairo(300, 300); d.DrawMolecule(flat); d.FinishDrawing()
    lig_img = Image.open(io.BytesIO(d.GetDrawingText()))

    fig, ax = plt.subplots(figsize=(8.5, 8.5), dpi=150)
    ax.set_xlim(-1.35, 1.35); ax.set_ylim(-1.35, 1.35); ax.axis("off")
    ax.set_title(title + (f"   (interactions: {source})" if source else ""), fontsize=12, fontweight="bold")

    # ligand centered
    ax.imshow(lig_img, extent=(-0.5, 0.5, -0.5, 0.5), zorder=3)

    # residues arranged on a ring (one bubble per residue+type, closest contact)
    inter = _dedupe_for_diagram(interactions or [])
    n = max(1, len(inter))
    R = 1.05
    for i, h in enumerate(inter):
        ang = 2 * math.pi * i / n + math.pi / 2
        x, y = R * math.cos(ang), R * math.sin(ang)
        typ = h.get("type", "hydrophobic")
        st = _STYLE.get(typ, _STYLE["hydrophobic"])
        # connector line ligand-edge -> residue
        ex, ey = 0.42 * math.cos(ang), 0.42 * math.sin(ang)
        ax.plot([ex, x * 0.78], [ey, y * 0.78], color=st["color"], ls=st["ls"], lw=st["lw"], zorder=2)
        if typ in ("hydrophobic", "alkyl", "pialkyl"):       # spiked arc marker
            for k in range(-2, 3):
                a2 = ang + k * 0.09
                ax.plot([x * 0.80, x * 0.80 + 0.05 * math.cos(a2)],
                        [y * 0.80, y * 0.80 + 0.05 * math.sin(a2)], color=st["color"], lw=1.0, zorder=2)
        # residue label + polarity halo
        resname = "".join([c for c in h["residue"] if c.isalpha()])[:3].upper()
        polar = resname in _POLAR_RES
        halo = "#c9b3e6" if polar else "#bfe3c2"
        ax.scatter([x], [y], s=760, color=halo, edgecolors="white", zorder=4)
        shared = ref_residues and h["residue"] in ref_residues
        ax.text(x, y, h["residue"] + (" *" if shared else ""), ha="center", va="center",
                fontsize=8.5, fontweight="bold" if shared else "normal", zorder=5)
        if h.get("distance") is not None:
            mx, my = (ex + x * 0.78) / 2, (ey + y * 0.78) / 2
            ax.text(mx, my, f'{h["distance"]}\u00c5', fontsize=6.5, color=st["color"], zorder=5)

    present = {h.get("type", "hydrophobic") for h in inter}
    legend = [Line2D([0], [0], color=_STYLE[t]["color"],
                     ls=_STYLE[t]["ls"] if _STYLE[t]["ls"] != "solid" else "-",
                     lw=2, label=_STYLE[t]["label"]) for t in _STYLE if t in present]
    legend += [Line2D([0], [0], marker="o", color="w", markerfacecolor="#c9b3e6", markersize=10, label="polar residue"),
               Line2D([0], [0], marker="o", color="w", markerfacecolor="#bfe3c2", markersize=10, label="non-polar residue")]
    if legend:
        ax.legend(handles=legend, loc="lower center", ncol=3, fontsize=8, frameon=False,
                  bbox_to_anchor=(0.5, -0.04))
    buf = io.BytesIO(); fig.savefig(buf, format="png", dpi=150, bbox_inches="tight"); plt.close(fig)
    return base64.b64encode(buf.getvalue()).decode()
