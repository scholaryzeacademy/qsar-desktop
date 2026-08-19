import { useState } from "react";
import type { AdvancedDockingState } from "../lib/useAdvancedDocking";

const STATUS_CLS: Record<string, string> = {
  muted: "text-inkmut",
  ok: "border-brand-300/50 bg-brand-500/[0.08] text-brand-800 rounded-lg border px-2.5 py-2",
  warn: "border-amber/30 bg-amber/10 text-amber rounded-lg border px-2.5 py-2",
  err: "text-clay",
};

export function AdvancedSettingsPanel({ adv, openByDefault = false }: { adv: AdvancedDockingState; openByDefault?: boolean }) {
  const [open, setOpen] = useState(openByDefault);

  return (
    <div className="mt-3.5 rounded-xl border border-line">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center justify-between px-3 py-2.5 text-left text-[12.5px] font-semibold text-brand-700"
      >
        Advanced Settings
        <svg
          viewBox="0 0 24 24"
          width="14"
          height="14"
          fill="none"
          stroke="currentColor"
          strokeWidth="2.4"
          className={`transition-transform ${open ? "rotate-180" : ""}`}
        >
          <path d="M6 9l6 6 6-6" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>
      {open && (
        <div className="border-t border-line px-3 pb-3 pt-2.5">
          <div className="mb-3">
            <label className="field-label">Manual structure (overrides the automatic recommendation)</label>
            <div className="max-h-[200px] overflow-y-auto rounded-lg border border-line">
              {adv.candidatesLoading && <div className="p-2 text-[12.5px] text-inkmut">Loading structural evidence…</div>}
              {!adv.candidatesLoading && adv.candidates?.length === 0 && (
                <div className="p-2 text-[12.5px] text-inkmut">No qualifying structures on record.</div>
              )}
              {!adv.candidatesLoading &&
                adv.candidates?.map((c) => {
                  const q = [
                    c.resolution != null ? `${c.resolution} Å` : null,
                    c.ligand_RSCC != null ? `RSCC ${c.ligand_RSCC}` : null,
                    c.ligand_RSR != null ? `RSR ${c.ligand_RSR}` : null,
                  ]
                    .filter(Boolean)
                    .join(" · ");
                  const on = adv.pickedPdb === c.pdb_id;
                  return (
                    <div
                      key={c.pdb_id}
                      onClick={() => adv.pickStructure(c.pdb_id, c.resname)}
                      className={`flex cursor-pointer items-center gap-2 border-b border-line/70 px-2.5 py-1.5 text-[12.5px] last:border-0 hover:bg-surface2/60 ${on ? "bg-brand-500/[0.08]" : ""}`}
                    >
                      <span className="min-w-[48px] font-bold text-ink">{c.pdb_id}</span>
                      <span className="flex-1 text-inkmut">
                        rank #{c.csv_rank ?? "?"} · {c.resname} · {q}
                      </span>
                      {c.is_current_default && <span className="badge bg-brand-500/15 text-brand-800">automatic default</span>}
                    </div>
                  );
                })}
            </div>
            {adv.structureStatus && <div className={`field-hint ${STATUS_CLS[adv.structureStatus.kind]}`}>{adv.structureStatus.text}</div>}
            <button type="button" className="btn-link mt-2" disabled={adv.autoValidateBusy} onClick={() => adv.runAutoValidate()}>
              {adv.autoValidateBusy ? "Testing candidate structures…" : "Find best validated structure automatically"}
            </button>
            {adv.autoValidateStatus && <div className={`field-hint ${STATUS_CLS[adv.autoValidateStatus.kind]}`}>{adv.autoValidateStatus.text}</div>}
          </div>

          <div className="mb-3">
            <label className="field-label">Exhaustiveness</label>
            <input
              type="number"
              min={1}
              max={64}
              placeholder="Automatic (8)"
              className="field-input"
              value={adv.exhaustiveness}
              onChange={(e) => adv.setExhaustiveness(e.target.value)}
            />
          </div>
          <div className="mb-3">
            <label className="field-label">Number of poses</label>
            <input
              type="number"
              min={1}
              max={20}
              placeholder="Automatic (9)"
              className="field-input"
              value={adv.nPoses}
              onChange={(e) => adv.setNPoses(e.target.value)}
            />
          </div>
          <div className="mb-3">
            <label className="flex cursor-pointer items-center gap-2 text-[12.5px] font-medium text-ink">
              <input type="checkbox" checked={adv.useGnina} onChange={(e) => adv.setUseGnina(e.target.checked)} />
              GNINA CNN rescoring (second opinion, if installed)
            </label>
          </div>
          <div className="mb-3">
            <label className="field-label">Binding box</label>
            <div className="field-hint">
              Automatic (ligand-centered) unless you drag it in "View binding site in 3D" above, or set it from selected residues.
            </div>
          </div>
          <button type="button" className="btn-link" onClick={() => adv.resetToAutomatic()}>
            Reset to Automatic
          </button>
        </div>
      )}
    </div>
  );
}
