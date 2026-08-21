import { useEffect, useRef, useState } from "react";
import { applyProteinStyle, clearSurfaces, fetchTextCached, get3Dmol, type ProteinStyle } from "../lib/mol3d";
import { StyleSelect } from "./StyleSelect";

/** Lightweight, read-only receptor preview — auto-rendered as soon as a
    target with docking data is picked (see TargetBrowser.tsx), so the
    default structure is visible without an extra click. Deliberately
    simpler than BindingSiteModal (no drag gizmo, no residue picker) —
    that richer editing view is still reachable via "View binding site
    in 3D" (DockingModeSection.tsx) for anyone who wants to fine-tune
    the box; this is just "here's what got auto-picked." */
export function ReceptorPreview({ receptorUrl, ligandUrl }: { receptorUrl?: string | null; ligandUrl?: string | null }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const viewerRef = useRef<any>(null);
  const surfaceIdsRef = useRef<number[]>([]);
  const [style, setStyle] = useState<ProteinStyle>("cartoon");

  // Full rebuild: new structure. Style itself is applied by the effect
  // below so switching styles doesn't refetch/re-parse the PDB/SDF.
  useEffect(() => {
    let cancelled = false;
    const container = containerRef.current;
    if (!container) return;
    container.innerHTML = "";
    viewerRef.current = null;
    surfaceIdsRef.current = [];
    if (!receptorUrl) return;
    (async () => {
      const $3Dmol = get3Dmol();
      if (!$3Dmol) {
        if (container) container.innerHTML = '<div class="p-2.5 text-[12px] text-inkmut">3D viewer unavailable.</div>';
        return;
      }
      const pdb = await fetchTextCached(receptorUrl);
      if (cancelled || !container || !pdb) return;
      const viewer = $3Dmol.createViewer(container, { backgroundColor: "white" });
      viewer.addModel(pdb, "pdb");
      let ligModel = 0;
      if (ligandUrl) {
        try {
          const sdf = await fetchTextCached(ligandUrl);
          if (cancelled || !container) return;
          if (sdf) {
            viewer.addModel(sdf, "sdf");
            ligModel = 1;
            viewer.setStyle({ model: 1 }, { stick: { radius: 0.18, colorscheme: "cyanCarbon" } });
          }
        } catch {
          /* optional */
        }
      }
      viewerRef.current = viewer;
      applyProteinStyle(viewer, { model: 0 }, style, (ids) => (surfaceIdsRef.current = ids));
      if (ligModel) viewer.zoomTo({ model: ligModel });
      else viewer.zoomTo();
      viewer.render();
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [receptorUrl, ligandUrl]);

  // Style-only change: reuse the already-loaded models.
  useEffect(() => {
    const viewer = viewerRef.current;
    if (!viewer) return;
    surfaceIdsRef.current = clearSurfaces(viewer, surfaceIdsRef.current);
    applyProteinStyle(viewer, { model: 0 }, style, (ids) => (surfaceIdsRef.current = ids));
    viewer.render();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [style]);

  if (!receptorUrl) return null;
  return (
    <div className="relative">
      <div ref={containerRef} className="relative h-[240px] w-full rounded-lg border border-line bg-white" />
      <div className="absolute right-1.5 top-1.5 z-10">
        <StyleSelect value={style} onChange={setStyle} />
      </div>
    </div>
  );
}
