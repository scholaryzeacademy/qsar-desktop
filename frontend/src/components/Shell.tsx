import { useAppData } from "../lib/AppDataContext";
import { AdmetIcon, CompareIcon, DockingIcon, LeafLattice, PredictIcon, ScreenIcon, TargetInfoIcon } from "./Icons";

export type TabId = "screen" | "predict" | "admet" | "compare" | "docking" | "target";

const TABS: { id: TabId; label: string; icon: (p: any) => JSX.Element }[] = [
  { id: "screen", label: "Screen", icon: ScreenIcon },
  { id: "predict", label: "Predict", icon: PredictIcon },
  { id: "admet", label: "ADMET", icon: AdmetIcon },
  { id: "compare", label: "Compare", icon: CompareIcon },
  { id: "docking", label: "Docking", icon: DockingIcon },
  { id: "target", label: "Target Info", icon: TargetInfoIcon },
];

export function Shell({ tab, onTab, children }: { tab: TabId; onTab: (t: TabId) => void; children: React.ReactNode }) {
  const { loading, error, targetCount } = useAppData();

  return (
    <div className="min-h-screen bg-canvas">
      <header className="sticky top-0 z-20 flex h-[58px] items-center gap-6 bg-brand-950 px-6 text-white shadow-card">
        <div className="flex items-center gap-2.5">
          <LeafLattice className="h-6 w-6 text-lime" />
          <span className="font-display text-[17px] font-semibold tracking-tight">PhytoScreen</span>
        </div>
        <nav className="flex h-full gap-1">
          {TABS.map((t) => {
            const Icon = t.icon;
            const active = tab === t.id;
            return (
              <button
                key={t.id}
                onClick={() => onTab(t.id)}
                className={`inline-flex h-full items-center gap-1.5 border-b-2 px-3.5 text-[13.5px] font-semibold transition-colors ${
                  active ? "border-lime text-white" : "border-transparent text-white/55 hover:text-white/85"
                }`}
              >
                <Icon className="h-[15px] w-[15px] opacity-90" />
                {t.label}
              </button>
            );
          })}
        </nav>
        <div className="ml-auto flex items-center gap-2 text-[12px] text-white/60">
          {error ? (
            <span className="text-clay/90">backend error</span>
          ) : loading ? (
            <span>connecting…</span>
          ) : (
            <>
              <span className="h-[7px] w-[7px] animate-pulseDot rounded-full bg-lime" />
              <b className="text-white/90">{targetCount}</b> targets loaded
            </>
          )}
        </div>
      </header>
      <main className="px-6 py-6">{children}</main>
    </div>
  );
}

export function TwoColLayout({ sidebar, children }: { sidebar: React.ReactNode; children: React.ReactNode }) {
  return (
    <div className="mx-auto grid max-w-[1280px] grid-cols-1 items-start gap-5 lg:grid-cols-[350px_1fr]">
      <aside className="card sticky top-[78px] max-h-[calc(100vh-96px)] overflow-y-auto p-[18px]">{sidebar}</aside>
      <main className="card min-h-[60vh] overflow-hidden">{children}</main>
    </div>
  );
}

export function SectionIntro({ title, sub }: { title: string; sub: string }) {
  return (
    <div className="mb-1">
      <h2 className="font-display text-[19px] font-medium text-ink">{title}</h2>
      <p className="mb-4 mt-0.5 text-[12.5px] text-inkmut">{sub}</p>
    </div>
  );
}

export function ResultHeader({ children }: { children: React.ReactNode }) {
  return <div className="flex flex-wrap items-center gap-x-6 gap-y-2.5 border-b border-line px-5 py-4">{children}</div>;
}
export function ResultName({ children }: { children: React.ReactNode }) {
  return <div className="font-display text-[16px] font-medium text-ink">{children}</div>;
}
export function Stat({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="text-[12px] text-inkmut">
      {label}
      <b className="block text-[15px] font-semibold text-ink">{children}</b>
    </div>
  );
}
