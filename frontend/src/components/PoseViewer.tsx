import { useEffect, useRef, useState } from "react";
import { fetchTextCached, get3Dmol } from "../lib/mol3d";
import { apiUrl } from "../lib/api";

export function PoseViewer({
  posePdb,
  receptorPdbPath,
  interactions,
}: {
  posePdb?: string | null;
  receptorPdbPath?: string | null;
  interactions?: { residue?: string }[];
}) {
  const [show, setShow] = useState(false);
  const [spin, setSpin] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const viewerRef = useRef<any>(null);
  const ligIdxRef = useRef(0);
  const initedRef = useRef(false);

  useEffect(() => {
    if (!show || initedRef.current) return;
    initedRef.current = true;
    (async () => {
      const $3Dmol = get3Dmol();
      if (!$3Dmol || !containerRef.current || !posePdb) {
        if (containerRef.current)
          containerRef.current.innerHTML = '<div style="padding:10px" class="text-inkmut text-sm">3D pose not available.</div>';
        return;
      }
      const receptorPdb = receptorPdbPath ? await fetchTextCached(apiUrl(`/api/docking/receptor_file?path=${encodeURIComponent(receptorPdbPath)}`)) : null;
      if (!containerRef.current) return;
      const viewer = $3Dmol.createViewer(containerRef.current, { backgroundColor: "white" });
      viewerRef.current = viewer;
      if (receptorPdb) {
        viewer.addModel(receptorPdb, "pdb");
        viewer.setStyle({ model: 0 }, { cartoon: { color: "lightgrey", opacity: 0.55 } });
        const resiList = [
          ...new Set(
            (interactions || [])
              .map((h) => {
                const m = (h.residue || "").match(/(\d+)$/);
                return m ? parseInt(m[1]) : null;
              })
              .filter((n): n is number => n != null)
          ),
        ];
        if (resiList.length) viewer.addStyle({ model: 0, resi: resiList }, { stick: { radius: 0.12, colorscheme: "grayCarbon" } });
      }
      viewer.addModel(posePdb, "pdb");
      const ligIdx = receptorPdb ? 1 : 0;
      ligIdxRef.current = ligIdx;
      viewer.setStyle({ model: ligIdx }, { stick: { radius: 0.16 }, sphere: { scale: 0.25 } });
      viewer.zoomTo({ model: ligIdx });
      viewer.render();
    })();
  }, [show, posePdb, receptorPdbPath, interactions]);

  useEffect(() => {
    viewerRef.current?.spin(spin ? "y" : false);
  }, [spin]);

  return (
    <div className="mt-2.5">
      <div className="flex flex-wrap items-center gap-2">
        <button type="button" className="btn-link" onClick={() => setShow((s) => !s)}>
          Ball-and-stick 3D pose
        </button>
        <button
          type="button"
          className="btn-link"
          onClick={() => {
            const v = viewerRef.current;
            if (!v) return;
            v.zoomTo({ model: ligIdxRef.current });
            v.render();
          }}
        >
          Reset view
        </button>
        <label className="flex cursor-pointer items-center gap-1.5 text-[12px] text-inkmut">
          <input type="checkbox" checked={spin} onChange={(e) => setSpin(e.target.checked)} />
          spin
        </label>
        <span className="text-[11px] text-inkmut">
          All atoms shown incl. hydrogens (nonpolar H positions are geometry-estimated, not Vina's own placement).
        </span>
      </div>
      {show && <div ref={containerRef} className="relative mt-2.5 h-[420px] w-full rounded-lg border border-line bg-white" />}
    </div>
  );
}
