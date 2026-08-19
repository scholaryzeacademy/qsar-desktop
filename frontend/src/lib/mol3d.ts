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

export const MIN_BOX_DIM = 4.0;

export const HANDLE_SPECS = [
  { key: "x1", axis: 0, sign: 1, color: "#ef4444" },
  { key: "x-1", axis: 0, sign: -1, color: "#ef4444" },
  { key: "y1", axis: 1, sign: 1, color: "#22c55e" },
  { key: "y-1", axis: 1, sign: -1, color: "#22c55e" },
  { key: "z1", axis: 2, sign: 1, color: "#3b82f6" },
  { key: "z-1", axis: 2, sign: -1, color: "#3b82f6" },
] as const;
