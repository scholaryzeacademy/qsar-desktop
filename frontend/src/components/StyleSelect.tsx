import { PROTEIN_STYLE_OPTIONS, type ProteinStyle } from "../lib/mol3d";

/** Shared style dropdown used by every 3D viewer (ReceptorPreview,
    PoseViewer, BindingSiteModal) — applies to the receptor/protein
    representation only; ligand/pose rendering is unaffected. */
export function StyleSelect({ value, onChange }: { value: ProteinStyle; onChange: (s: ProteinStyle) => void }) {
  return (
    <select
      className="field-input h-auto w-auto py-1 text-[12px]"
      value={value}
      onChange={(e) => onChange(e.target.value as ProteinStyle)}
      title="Protein representation"
    >
      {PROTEIN_STYLE_OPTIONS.map((o) => (
        <option key={o.value} value={o.value}>
          {o.label}
        </option>
      ))}
    </select>
  );
}
