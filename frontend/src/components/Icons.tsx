import type { SVGProps } from "react";

const base: SVGProps<SVGSVGElement> = {
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 2,
  strokeLinecap: "round",
  strokeLinejoin: "round",
};

export function ScreenIcon(p: SVGProps<SVGSVGElement>) {
  return (
    <svg {...base} {...p}>
      <path d="M9 2v6L4 20a1 1 0 0 0 1 2h14a1 1 0 0 0 1-2L15 8V2M9 2h6M8 14h8" />
    </svg>
  );
}
export function PredictIcon(p: SVGProps<SVGSVGElement>) {
  return (
    <svg {...base} {...p}>
      <circle cx="12" cy="12" r="9" />
      <circle cx="12" cy="12" r="4" />
      <circle cx="12" cy="12" r=".5" fill="currentColor" />
    </svg>
  );
}
export function AdmetIcon(p: SVGProps<SVGSVGElement>) {
  return (
    <svg {...base} {...p}>
      <path d="M3 12h4l2 8 4-16 2 8h6" />
    </svg>
  );
}
export function CompareIcon(p: SVGProps<SVGSVGElement>) {
  return (
    <svg {...base} {...p}>
      <path d="M4 20V10M12 20V4M20 20v-7" />
    </svg>
  );
}
export function DockingIcon(p: SVGProps<SVGSVGElement>) {
  return (
    <svg {...base} {...p}>
      <circle cx="6" cy="6" r="2.5" />
      <circle cx="18" cy="18" r="2.5" />
      <path d="M8 7.5C10 10 14 14 16 16.5" />
      <path d="M6.5 9c1.5 0 3 .5 4 1.5M17.5 15c-1.5 0-3-.5-4-1.5" />
    </svg>
  );
}
export function TargetInfoIcon(p: SVGProps<SVGSVGElement>) {
  return (
    <svg {...base} {...p}>
      <rect x="4" y="3" width="16" height="18" rx="2" />
      <path d="M8 8h8M8 12h8M8 16h5" />
    </svg>
  );
}

/** Signature mark: a leaf silhouette built from a molecular node lattice —
    phyto (leaf) + chem (bonds/atoms) in one motif. Reused as the brand
    mark, empty-state watermark, and loading spinner. */
export function LeafLattice({ className = "h-6 w-6", spin = false }: { className?: string; spin?: boolean }) {
  return (
    <svg
      viewBox="0 0 40 40"
      className={`${className} ${spin ? "animate-spinLattice" : ""}`}
      fill="none"
    >
      <path
        d="M20 4C10 6 5 14 6 24c0.5 5 4 9 9 10 10 2 19-5 21-15C38 11 30 3 20 4Z"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinejoin="round"
        opacity="0.9"
      />
      <path d="M20 4C15 12 12 22 15 34" stroke="currentColor" strokeWidth="1.3" opacity="0.55" />
      <g stroke="currentColor" strokeWidth="1.3" opacity="0.85">
        <path d="M20 4L26 12M26 12L23 20M23 20L15 22M15 22L12 16M12 16L20 4" />
        <path d="M23 20L28 26M15 22L18 30" />
      </g>
      <g fill="currentColor">
        <circle cx="20" cy="4" r="1.6" />
        <circle cx="26" cy="12" r="1.6" />
        <circle cx="23" cy="20" r="1.6" />
        <circle cx="15" cy="22" r="1.6" />
        <circle cx="12" cy="16" r="1.6" />
        <circle cx="28" cy="26" r="1.4" />
        <circle cx="18" cy="30" r="1.4" />
      </g>
    </svg>
  );
}
