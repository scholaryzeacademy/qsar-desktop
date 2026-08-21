// Small shared helpers for the two 3Dmol.js integrations (binding-site
// viewer w/ drag gizmo, and the docking-result ball-and-stick pose viewer).
// 3Dmol is loaded globally via the vendored <script> tag (see index.html) —
// there's no npm package dependency, matching the original app.

declare global {
  interface Window {
    $3Dmol: any;
  }
}

export function get3Dmol(): any | null {
  return typeof window !== "undefined" && window.$3Dmol ? window.$3Dmol : null;
}

const _textCache = new Map<string, Promise<string | null>>();
export function fetchTextCached(url: string): Promise<string | null> {
  if (!_textCache.has(url)) {
    _textCache.set(
      url,
      fetch(url)
        .then((r) => (r.ok ? r.text() : null))
        .catch(() => null)
    );
  }
  return _textCache.get(url)!;
}

export function drawBoxShapes(viewer: any, center: [number, number, number], size: [number, number, number]) {
  if (!center || !size) return;
  viewer.addBox({
    center: { x: center[0], y: center[1], z: center[2] },
    dimensions: { w: size[0], h: size[1], d: size[2] },
    color: "red",
    opacity: 0.15,
  });
  viewer.addBox({
    center: { x: center[0], y: center[1], z: center[2] },
    dimensions: { w: size[0], h: size[1], d: size[2] },
    color: "red",
    wireframe: true,
    linewidth: 2,
  });
}

/** Combines a receptor PDB and a docked ligand-pose PDB into one
    downloadable "complex" file — same two structures PoseViewer already
    loads as separate 3Dmol models for VISUALIZATION, just concatenated
    as text for a real file. Strips any existing END/ENDMDL from each
    part (so the receptor's own terminator doesn't cut the file short)
    and adds a TER between chains plus a single trailing END. */
export function combinePdbText(receptorPdb: string, posePdb: string): string {
  const strip = (s: string) =>
    s
      .split("\n")
      .filter((line) => !/^(END|ENDMDL)\s*$/.test(line.trim()))
      .join("\n")
      .replace(/\n+$/, "");
  return `${strip(receptorPdb)}\nTER\n${strip(posePdb)}\nEND\n`;
}

export const MIN_BOX_DIM = 4.0;

/** Protein representation styles offered by the style switcher in every
    3D viewer (ReceptorPreview, PoseViewer, BindingSiteModal). "surface"
    variants and "mesh" go through addSurface — heavier than the atom/
    bond styles, and need their own cleanup (see clearSurfaces) since
    3Dmol tracks them separately from setStyle. */
export type ProteinStyle = "cartoon" | "stick" | "line" | "sphere" | "surface" | "surfaceHydrophobicity" | "mesh";

export const PROTEIN_STYLE_OPTIONS: { value: ProteinStyle; label: string }[] = [
  { value: "cartoon", label: "Ribbon (cartoon)" },
  { value: "stick", label: "Stick" },
  { value: "line", label: "Line" },
  { value: "sphere", label: "Sphere" },
  { value: "surface", label: "Surface" },
  { value: "surfaceHydrophobicity", label: "Hydrophobicity surface" },
  { value: "mesh", label: "Mesh" },
];

// Kyte & Doolittle hydrophobicity scale (most positive = most hydrophobic).
const KD_SCALE: Record<string, number> = {
  ILE: 4.5, VAL: 4.2, LEU: 3.8, PHE: 2.8, CYS: 2.5, MET: 1.9, ALA: 1.8,
  GLY: -0.4, THR: -0.7, SER: -0.8, TRP: -0.9, TYR: -1.3, PRO: -1.6,
  HIS: -3.2, GLU: -3.5, GLN: -3.5, ASP: -3.5, ASN: -3.5, LYS: -3.9, ARG: -4.5,
};

function lerp(a: number, b: number, t: number): number {
  return a + (b - a) * t;
}

/** Blue (hydrophilic) -> white -> orange (hydrophobic), same convention
    PyMOL/Chimera use for this coloring — unrecognised residues (ligand
    atoms, waters, etc.) render neutral white rather than crashing. */
function hydrophobicityColor(resn: string | undefined): string {
  const v = KD_SCALE[(resn || "").toUpperCase()];
  if (v === undefined) return "#e5e7eb";
  const t = (v + 4.5) / 9; // -4.5..4.5 -> 0..1
  const lo = { r: 0x2b, g: 0x6c, b: 0xb0 }; // blue
  const mid = { r: 0xff, g: 0xff, b: 0xff }; // white
  const hi = { r: 0xe2, g: 0x7d, b: 0x2a }; // orange
  const [a, b, u] = t < 0.5 ? [lo, mid, t / 0.5] : [mid, hi, (t - 0.5) / 0.5];
  const r = Math.round(lerp(a.r, b.r, u));
  const g = Math.round(lerp(a.g, b.g, u));
  const bl = Math.round(lerp(a.b, b.b, u));
  return `#${[r, g, bl].map((x) => x.toString(16).padStart(2, "0")).join("")}`;
}

/** Removes every surface this viewer is currently tracking — call before
    applying a non-surface style, and before adding a new surface (3Dmol
    layers surfaces rather than replacing them, so switching from one
    surface style to another without this leaves the old one behind). */
export function clearSurfaces(viewer: any, ids: number[]): number[] {
  for (const id of ids) {
    try {
      viewer.removeSurface(id);
    } catch {
      /* already gone */
    }
  }
  return [];
}

/** Applies one of PROTEIN_STYLE_OPTIONS to `sel` (a 3Dmol selection spec,
    e.g. {model: 0}). Non-surface styles resolve synchronously; surface
    styles are async in 3Dmol (addSurface returns before the mesh is
    built) — pass the returned surface id(s) to clearSurfaces() later via
    onSurfaceIds, and call viewer.render() again once it resolves (3Dmol
    does this internally too, but an explicit render right after keeps
    the underlying atom style visible immediately instead of blank). */
export function applyProteinStyle(viewer: any, sel: any, style: ProteinStyle, onSurfaceIds?: (ids: number[]) => void): void {
  switch (style) {
    case "cartoon":
      viewer.setStyle(sel, { cartoon: { color: "lightgrey" } });
      break;
    case "stick":
      viewer.setStyle(sel, { stick: { radius: 0.15, colorscheme: "grayCarbon" } });
      break;
    case "line":
      viewer.setStyle(sel, { line: {} });
      break;
    case "sphere":
      viewer.setStyle(sel, { sphere: { scale: 0.3, colorscheme: "grayCarbon" } });
      break;
    case "surface": {
      viewer.setStyle(sel, { cartoon: { color: "lightgrey" } });
      const id = viewer.addSurface("VDW", { opacity: 0.85, color: "white" }, sel);
      onSurfaceIds?.([id]);
      break;
    }
    case "surfaceHydrophobicity": {
      viewer.setStyle(sel, { cartoon: { color: "lightgrey" } });
      const id = viewer.addSurface("VDW", { opacity: 0.9, colorfunc: (atom: any) => hydrophobicityColor(atom?.resn) }, sel);
      onSurfaceIds?.([id]);
      break;
    }
    case "mesh": {
      viewer.setStyle(sel, { cartoon: { color: "lightgrey" } });
      const id = viewer.addSurface("SES", { opacity: 1, wireframe: true, color: "#6b7280" }, sel);
      onSurfaceIds?.([id]);
      break;
    }
  }
}

export const HANDLE_SPECS = [
  { key: "x1", axis: 0, sign: 1, color: "#ef4444" },
  { key: "x-1", axis: 0, sign: -1, color: "#ef4444" },
  { key: "y1", axis: 1, sign: 1, color: "#22c55e" },
  { key: "y-1", axis: 1, sign: -1, color: "#22c55e" },
  { key: "z1", axis: 2, sign: 1, color: "#3b82f6" },
  { key: "z-1", axis: 2, sign: -1, color: "#3b82f6" },
] as const;
