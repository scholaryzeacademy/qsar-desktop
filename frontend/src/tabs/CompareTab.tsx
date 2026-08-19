import { useState } from "react";
import * as api from "../lib/api";
import { useAppData } from "../lib/AppDataContext";
import { useMoleculeInput } from "../lib/useMoleculeInput";
import { MoleculeInputPanel } from "../components/MoleculeInputPanel";
import { SectionIntro } from "../components/Shell";
import { Disclaimer, EmptyState, ErrorBox, Spinner } from "../components/Feedback";
import { SegmentedToggle } from "../components/SegmentedToggle";
import type { CompareResponse } from "../lib/types";

const VIEWS = [
  { value: "matrix", label: "Matrix" },
  { value: "ranking", label: "Ranking" },
  { value: "selective", label: "Selective" },
  { value: "multi", label: "Multi-target" },
  { value: "best", label: "Best/target" },
  { value: "admet", label: "ADMET" },
];

function heatColor(v: number | null, inDom: boolean) {
  if (!inDom || v == null) return "#f1f5f9";
  const t = Math.max(0, Math.min(1, (v - 4.5) / 3.5));
  return `rgba(${Math.round(220 - 176 * t)},${Math.round(120 + 42 * t)},${Math.round(90 + 5 * t)},${0.2 + 0.28 * t})`;
}

export function CompareTab() {
  const { targets } = useAppData();
  const [checked, setChecked] = useState<Set<string>>(new Set());
  const mol = useMoleculeInput();
  const [state, setState] = useState<"idle" | "loading" | "error" | "done">("idle");
  const [error, setError] = useState("");
  const [data, setData] = useState<CompareResponse | null>(null);
  const [view, setView] = useState("matrix");

  const toggle = (id: string) =>
    setChecked((s) => {
      const n = new Set(s);
      n.has(id) ? n.delete(id) : n.add(id);
      return n;
    });

  const run = async () => {
    setState("loading");
    setError("");
    try {
      const smiles = await mol.resolve();
      if (!smiles.length) throw new Error("Enter SMILES.");
      if (!checked.size) throw new Error("Pick at least one target.");
      const d = await api.predictMulti(smiles, [...checked]);
      setData(d);
      setView("matrix");
      setState("done");
    } catch (e: any) {
      setError(e.message || "Error");
      setState("error");
    }
  };

  return (
    <div className="mx-auto grid max-w-[1280px] grid-cols-1 items-start gap-5 lg:grid-cols-[350px_1fr]">
      <aside className="card sticky top-[78px] max-h-[calc(100vh-96px)] overflow-y-auto p-[18px]">
        <SectionIntro title="Compare targets" sub="Screen against several targets." />
        <label className="field-label">Pick targets</label>
        <div className="max-h-[180px] overflow-y-auto rounded-lg border border-line p-2">
          {targets.map((t) => (
            <label key={t.target_id} className="flex items-center gap-2 px-0.5 py-[3px] text-[13px]">
              <input type="checkbox" checked={checked.has(t.target_id)} onChange={() => toggle(t.target_id)} /> {t.target_id}
            </label>
          ))}
        </div>
        <div className="mt-3">
          <MoleculeInputPanel state={mol} />
        </div>
        <button className="btn-primary mt-[18px]" onClick={run} disabled={state === "loading"}>
          Compare
        </button>
      </aside>
      <main className="card min-h-[60vh] overflow-hidden">
        {state === "idle" && <EmptyState title="Compare across targets" hint="Choose targets, then enter molecules." />}
        {state === "loading" && <Spinner />}
        {state === "error" && <ErrorBox message={error} />}
        {state === "done" && data && <CompareResults d={data} view={view} setView={setView} />}
      </main>
    </div>
  );
}

function CompareResults({ d, view, setView }: { d: CompareResponse; view: string; setView: (v: string) => void }) {
  const tid = d.targets.map((t) => t.target_id);
  return (
    <div>
      <Disclaimer>{d.disclaimer}</Disclaimer>
      <div className="px-5">
        <div className="max-w-[620px]">
          <SegmentedToggle value={view} onChange={setView} options={VIEWS} />
        </div>
      </div>
      <div className="mt-3 max-h-[calc(100vh-320px)] overflow-auto px-5 pb-5">
        {view === "matrix" && (
          <table className="w-full border-collapse text-[13px]">
            <thead>
              <tr>
                <Th>Compound</Th>
                {tid.map((t) => (
                  <Th key={t}>{t}</Th>
                ))}
                <Th>In-dom</Th>
              </tr>
            </thead>
            <tbody>
              {d.matrix.map((r, i) => (
                <tr key={i}>
                  <Td className="smi-mono">{r.smiles || r.input_smiles}</Td>
                  {tid.map((t) => {
                    const c = r.cells[t];
                    return (
                      <Td key={t}>
                        {c.in_domain && c.pred != null ? (
                          <span className="inline-block min-w-[64px] rounded-md px-2 py-1 text-center font-semibold" style={{ background: heatColor(c.pred, true) }}>
                            {c.pred}
                          </span>
                        ) : (
                          <span className="italic text-inkmut">{c.pred ?? "—"}</span>
                        )}
                      </Td>
                    );
                  })}
                  <Td>
                    {r.coverage.in_domain_targets}/{r.coverage.total_targets}
                  </Td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {view === "ranking" && (
          <table className="w-full border-collapse text-[13px]">
            <thead>
              <tr>
                <Th>#</Th>
                <Th>Compound</Th>
                <Th>Targets hit</Th>
                <Th>Mean predicted</Th>
                <Th>Coverage</Th>
              </tr>
            </thead>
            <tbody>
              {d.consensus_ranking.length ? (
                d.consensus_ranking.map((r) => (
                  <tr key={r.consensus_rank}>
                    <Td>{r.consensus_rank}</Td>
                    <Td className="smi-mono">{r.smiles}</Td>
                    <Td>{r.n_active}</Td>
                    <Td className="font-semibold">{r.mean_pred}</Td>
                    <Td>{r.coverage}</Td>
                  </tr>
                ))
              ) : (
                <tr>
                  <Td colSpan={5} className="text-inkmut">
                    No in-domain compounds.
                  </Td>
                </tr>
              )}
            </tbody>
          </table>
        )}
        {view === "selective" &&
          (d.selective_candidates.length ? (
            <table className="w-full border-collapse text-[13px]">
              <thead>
                <tr>
                  <Th>Compound</Th>
                  <Th>Selective for</Th>
                  <Th>Predicted</Th>
                  <Th>Gap</Th>
                </tr>
              </thead>
              <tbody>
                {d.selective_candidates.map((r, i) => (
                  <tr key={i}>
                    <Td className="smi-mono">{r.smiles}</Td>
                    <Td>{r.target}</Td>
                    <Td>{r.pred}</Td>
                    <Td className="font-semibold">{r.gap}</Td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <div className="py-16 text-center text-inkmut">No compound was selective (≥{d.selective_gap} log gap) for one target.</div>
          ))}
        {view === "multi" &&
          (d.multi_target_candidates.length ? (
            <table className="w-full border-collapse text-[13px]">
              <thead>
                <tr>
                  <Th>Compound</Th>
                  <Th>Active on</Th>
                  <Th># active</Th>
                  <Th>Mean predicted</Th>
                </tr>
              </thead>
              <tbody>
                {d.multi_target_candidates.map((r, i) => (
                  <tr key={i}>
                    <Td className="smi-mono">{r.smiles}</Td>
                    <Td>{r.active_targets.join(", ")}</Td>
                    <Td className="font-semibold">{r.n_active}</Td>
                    <Td>{r.mean_pred}</Td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <div className="py-16 text-center text-inkmut">No multi-target candidates (active on ≥2 targets at pIC50≥{d.active_cut}).</div>
          ))}
        {view === "best" &&
          tid.map((t) => (
            <div key={t} className="py-1.5">
              <div className="px-3 py-1.5 font-semibold">{t}</div>
              <table className="w-full border-collapse text-[13px]">
                <tbody>
                  {(d.best_per_target[t] || []).length ? (
                    d.best_per_target[t].map((x, i) => (
                      <tr key={i}>
                        <Td className="w-8">{i + 1}</Td>
                        <Td className="smi-mono">{x.smiles}</Td>
                        <Td className="w-16">{x.pred}</Td>
                      </tr>
                    ))
                  ) : (
                    <tr>
                      <Td className="text-inkmut">no in-domain compound</Td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          ))}
        {view === "admet" && (
          <table className="w-full border-collapse text-[13px]">
            <thead>
              <tr>
                <Th>Compound</Th>
                <Th>MW</Th>
                <Th>LogP</Th>
                <Th>QED</Th>
                <Th>Lipinski</Th>
                <Th>Alerts</Th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(d.admet).map(([s, p]) =>
                p.parsed_ok ? (
                  <tr key={s}>
                    <Td className="smi-mono">{s}</Td>
                    <Td>{p.physicochemical!.mw}</Td>
                    <Td>{p.physicochemical!.logp}</Td>
                    <Td>{p.physicochemical!.qed}</Td>
                    <Td>
                      <span className={`badge ${p.drug_likeness_flags!.lipinski_pass ? "bg-brand-500/15 text-brand-800" : "bg-amber/15 text-amber"}`}>
                        {p.drug_likeness_flags!.lipinski_violations}
                      </span>
                    </Td>
                    <Td>
                      <span className={`badge ${p.n_alerts ? "bg-amber/15 text-amber" : "bg-brand-500/15 text-brand-800"}`}>{p.n_alerts}</span>
                    </Td>
                  </tr>
                ) : null
              )}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

function Th({ children }: { children: React.ReactNode }) {
  return <th className="sticky top-0 z-10 border-b border-line bg-surface2 px-3 py-2.5 text-left text-[10.5px] font-semibold uppercase tracking-wide text-inkmut">{children}</th>;
}
function Td({ children, className = "", colSpan }: { children: React.ReactNode; className?: string; colSpan?: number }) {
  return (
    <td colSpan={colSpan} className={`border-b border-surface2 px-3 py-2.5 ${className}`}>
      {children}
    </td>
  );
}
