import type { MoleculeInputState } from "../lib/useMoleculeInput";
import { SegmentedToggle } from "./SegmentedToggle";

export function MoleculeInputPanel({ state, minHeight = 120 }: { state: MoleculeInputState; minHeight?: number }) {
  return (
    <div>
      <label className="field-label">Input</label>
      <SegmentedToggle
        value={state.mode}
        onChange={(v) => state.setMode(v as any)}
        options={[
          { value: "paste", label: "Paste" },
          { value: "csv", label: "CSV file" },
          { value: "sdf", label: "SDF file" },
        ]}
      />
      <div className="mt-2">
        {state.mode === "paste" && (
          <textarea
            className="field-input font-mono text-[12.5px] resize-y"
            style={{ minHeight }}
            placeholder="One SMILES per line"
            value={state.pasteText}
            onChange={(e) => state.setPasteText(e.target.value)}
          />
        )}
        {state.mode === "csv" && (
          <div>
            <input
              type="file"
              accept=".csv"
              className="field-input file:mr-3 file:rounded-md file:border-0 file:bg-brand-700 file:px-3 file:py-1.5 file:text-white file:font-semibold file:text-[12px] cursor-pointer"
              onChange={(e) => state.setCsvFile(e.target.files?.[0] ?? null)}
            />
            <div className="field-hint">Needs a SMILES column.</div>
          </div>
        )}
        {state.mode === "sdf" && (
          <div>
            <input
              type="file"
              accept=".sdf,.mol,.sd"
              className="field-input file:mr-3 file:rounded-md file:border-0 file:bg-brand-700 file:px-3 file:py-1.5 file:text-white file:font-semibold file:text-[12px] cursor-pointer"
              onChange={(e) => state.setSdfFile(e.target.files?.[0] ?? null)}
            />
            <div className="field-hint">Structure-data file — parsed server-side with RDKit.</div>
          </div>
        )}
      </div>
    </div>
  );
}
