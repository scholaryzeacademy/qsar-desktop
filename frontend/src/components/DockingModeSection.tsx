import { useState } from "react";
import type { AdvancedDockingState } from "../lib/useAdvancedDocking";
import { SegmentedToggle } from "./SegmentedToggle";
import { BindingSiteModal } from "./BindingSiteModal";

export function DockingModeSection({ adv, targetId }: { adv: AdvancedDockingState; targetId: string }) {
  const [modalOpen, setModalOpen] = useState(false);
  const { site, dockingMode, setDockingMode } = adv;

  let summary: React.ReactNode = <span className="text-inkmut">No binding-site evidence for this target.</span>;
  let showBtn = false;
  if (site) {
    if (dockingMode === "blind") {
      if (site.blind_box_size) {
        summary = (
          <>
            Blind docking: whole-protein search box{" "}
            <b>{site.blind_box_size.map((v) => v.toFixed(0)).join(" × ")}</b> Å — no pocket assumed.
          </>
        );
        showBtn = true;
      } else {
        summary = <span className="text-inkmut">Blind box unavailable — no prepared receptor on disk for this target.</span>;
      }
    } else {
      const n = site.residues.length;
      summary = (
        <>
          Binding site: <b>{n}</b> pocket residue(s) within 5 Å of the reference ligand (automatic) · box{" "}
          {site.box_size?.map((v) => v.toFixed(1)).join(" × ")} Å
        </>
      );
      showBtn = true;
    }
  } else if (targetId.startsWith("GENE_")) {
    summary = (
      <span className="text-inkmut">
        No automatic default yet for this target — pick a structure below (Advanced Settings), or click "Find best
        validated structure automatically".
      </span>
    );
  }

  return (
    <div>
      <label className="field-label">Docking mode</label>
      <SegmentedToggle
        value={dockingMode}
        onChange={(v) => setDockingMode(v as any)}
        options={[
          { value: "site_specific", label: "Site-specific" },
          { value: "blind", label: "Blind (whole protein)" },
        ]}
      />
      <div className="field-hint">{summary}</div>
      {showBtn && (
        <button type="button" className="btn-link mt-1.5" onClick={() => setModalOpen(true)}>
          <svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" strokeWidth="2">
            <circle cx="6" cy="6" r="2.2" />
            <circle cx="18" cy="18" r="2.2" />
            <path d="M8 7.5C10 10 14 14 16 16.5" />
          </svg>
          View binding site in 3D
        </button>
      )}
      {modalOpen && <BindingSiteModal adv={adv} targetId={targetId} onClose={() => setModalOpen(false)} />}
    </div>
  );
}
