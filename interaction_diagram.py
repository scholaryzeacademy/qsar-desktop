"""
LigPlot+/Discovery-Studio-style 2D interaction diagram.  [renderer TESTED; PLIP detection = validate-on-your-machine]

Detection:
  * If PLIP is installed, use it for ACCURATE interaction typing (H-bond,
    pi-stacking, hydrophobic, salt-bridge, halogen) on the protein-ligand
    complex. PLIP is the gold standard for detection.
  * Otherwise fall back to the built-in distance-based detector.

Rendering (follows the universal 2D-diagram conventions):
  * Central ligand drawn flat (RDKit 2D depiction).
  * Pink/purple DASHED lines  -> hydrogen bonds.
  * Green SOLID lines         -> pi-pi stacking.
  * Grey SPIKED arcs          -> hydrophobic contacts.
  * Residues labelled 3-letter + number (e.g. LEU144, GLY219), placed around
    the ligand, with polar (purple) / non-polar (green) colouring.
  * Legend included.
NOTE: this is a schematic in that style, not a pixel-identical LigPlot+ clone.
"""
import io, os, base64, math, tempfile, subprocess
import numpy as np
from rdkit import Chem
from rdkit.Chem import AllChem
from rdkit.Chem.Draw import rdMolDraw2D

# residue polarity for halo colouring
_POLAR_RES = {"ARG","LYS","ASP","GLU","GLN","ASN","HIS","SER","THR","TYR","CYS","TRP"}
_STYLE = {"hbond":     {"color": "#d63384", "ls": (0,(4,3)), "lw": 1.8, "label": "H-bond"},
          "pistacking":{"color": "#198754", "ls": "solid",   "lw": 2.0, "label": "pi-pi stacking"},
          "hydrophobic":{"color":"#8a8a8a", "ls": (0,(1,2)), "lw": 1.3, "label": "Hydrophobic"},
          "saltbridge":{"color": "#fd7e14", "ls": (0,(5,2)), "lw": 2.0, "label": "Salt bridge"},
          "halogen":   {"color": "#0dcaf0", "ls": (0,(4,3)), "lw": 1.8, "label": "Halogen"}}


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
            rec = open(receptor_pdb).read().rstrip()
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
            for h in site.hbonds_ldon + site.hbonds_pdon:
                out.append({"residue": f"{h.restype}{h.resnr}", "type": "hbond", "distance": round(h.distance_ad, 2)})
            for p in site.pistacking:
                out.append({"residue": f"{p.restype}{p.resnr}", "type": "pistacking", "distance": round(p.distance, 2)})
            for hc in site.hydrophobic_contacts:
                out.append({"residue": f"{hc.restype}{hc.resnr}", "type": "hydrophobic", "distance": round(hc.distance, 2)})
            for sb in site.saltbridge_lneg + site.saltbridge_pneg:
                out.append({"residue": f"{sb.restype}{sb.resnr}", "type": "saltbridge", "distance": round(sb.distance, 2)})
            for hal in getattr(site, "halogen_bonds", []):
                out.append({"residue": f"{hal.restype}{hal.resnr}", "type": "halogen", "distance": round(hal.distance, 2)})
            # dedupe by residue+type keeping closest
            best = {}
            for h in out:
                k = (h["residue"], h["type"])
                if k not in best or h["distance"] < best[k]["distance"]:
                    best[k] = h
            return list(best.values())
    except Exception:
        return None


def detect_interactions(receptor_pdb, pose_mol):
    """PLIP if available, else the built-in distance-based detector."""
    if plip_available():
        res = detect_with_plip(receptor_pdb, pose_mol)
        if res is not None:
            return res, "PLIP"
    try:
        from .interactions import detect_interactions as _dist
    except Exception:
        from interactions import detect_interactions as _dist
    return _dist(pose_mol, receptor_pdb), "distance-based"


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

    # residues arranged on a ring
    inter = interactions or []
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
        if typ == "hydrophobic":       # spiked arc marker
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
