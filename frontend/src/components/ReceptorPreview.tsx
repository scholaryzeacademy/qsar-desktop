import { useEffect, useRef } from "react";
import { fetchTextCached, get3Dmol } from "../lib/mol3d";

/** Lightweight, read-only receptor preview — auto-rendered as soon as a
    target with docking data is picked (see TargetBrowser.tsx), so the
    default structure is visible without an extra click. Deliberately
    simpler than BindingSiteModal (no drag gizmo, no residue picker) —
    that richer editing view is still reachable via "View binding site
    in 3D" (DockingModeSection.tsx) for anyone who wants to fine-tune
    the box; this is just "here's what got auto-picked." */
export function ReceptorPreview({ receptorUrl, ligandUrl }: { receptorUrl?: string | null; ligandUrl?: string | null }) {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let cancelled = false;
    const container = containerRef.current;
    if (!container) return;
    container.innerHTML = "";
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
      viewer.setStyle({ model: 0 }, { cartoon: { color: "lightgrey" } });
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
      if (ligModel) viewer.zoomTo({ model: ligModel });
      else viewer.zoomTo();
      viewer.render();
    })();
    return () => {
      cancelled = true;
    };
  }, [receptorUrl, ligandUrl]);

  if (!receptorUrl) return null;
  return <div ref={containerRef} className="relative h-[240px] w-full rounded-lg border border-line bg-white" />;
}
