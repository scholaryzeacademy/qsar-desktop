import { useState } from "react";
import * as api from "../lib/api";
import { useMoleculeInput } from "../lib/useMoleculeInput";
import { MoleculeInputPanel } from "../components/MoleculeInputPanel";
import { PlainTargetSelect } from "../components/TargetPicker";
import { ResultHeader, ResultName, SectionIntro, Stat } from "../components/Shell";
import { Disclaimer, EmptyState, ErrorBox, Spinner, ConfidenceDot } from "../components/Feedback";
import type { PredictResponse } from "../lib/types";

function toCsv(d: PredictResponse) {
  const rows = [["rank", "smiles", "predicted_pIC50", "ad_z", "confidence"]];
  d.in_domain.forEach((r) => rows.push([String(r.rank), r.smiles || "", String(r.predicted_pIC50 ?? ""), String(r.ad_z ?? ""), r.confidence_label || ""]));
  return rows.map((r) => r.map((x) => `"${x ?? ""}"`).join(",")).join("\n");
}
function downloadCsv(csv: string, name: string) {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([csv], { type: "text/csv" }));
  a.download = name;
  a.click();
}

export function PredictTab() {
  const [targetId, setTargetId] = useState("");
  const mol = useMoleculeInput();
  const [state, setState] = useState<"idle" | "loading" | "error" | "done">("idle");
  const [error, setError] = useState("");
  const [data, setData] = useState<PredictResponse | null>(null);

  const run = async () => {
    setState("loading");
    setError("");
    try {
      const smiles = await mol.resolve();
      if (!smiles.length) throw new Error("Enter at least one SMILES.");
      const d = await api.predict(targetId, smiles);
      setData(d);
      setState("done");
    } catch (e: any) {
      setError(e.message || "Error");
      setState("error");
    }
  };

  return (
    <div className="mx-auto grid max-w-[1280px] grid-cols-1 items-start gap-5 lg:grid-cols-[350px_1fr]">
      <aside className="card sticky top-[78px] max-h-[calc(100vh-96px)] overflow-y-auto p-[18px]">
        <SectionIntro title="Predict potency" sub="QSAR only, one target's shipped model." />
        <PlainTargetSelect targetId={targetId} onChange={setTargetId} />
        <div className="mt-3">
          <MoleculeInputPanel state={mol} />
        </div>
        <button className="btn-primary mt-[18px]" onClick={run} disabled={state === "loading"}>
          Rank compounds
        </button>
      </aside>
      <main className="card min-h-[60vh] overflow-hidden">
        {state === "idle" && <EmptyState title="Rank your candidates" hint="Select a target and enter molecules to rank." />}
        {state === "loading" && <Spinner />}
        {state === "error" && <ErrorBox message={error} />}
        {state === "done" && data && <PredictResults d={data} />}
      </main>
    </div>
  );
}

function PredictResults({ d }: { d: PredictResponse }) {
  const m = d.model_metrics;
  const c = d.counts;
  return (
    <div>
      <ResultHeader>
        <ResultName>{d.target.name}</ResultName>
        <Stat label="Model">{d.model || "—"}</Stat>
        <Stat label="Test R²">{m.test_r2 ?? "—"}</Stat>
        <Stat label="Test RMSE">{m.test_rmse ?? "—"}</Stat>
        <Stat label="Tropsha">{m.tropsha_pass === true ? "pass" : m.tropsha_pass === false ? "fail" : "—"}</Stat>
        <Stat label="In-domain">
          {c.in_domain}/{c.submitted}
        </Stat>
      </ResultHeader>
      <Disclaimer>{d.disclaimer}</Disclaimer>
      {d.in_domain.length ? (
        <>
          <div className="max-h-[calc(100vh-260px)] overflow-y-auto overflow-x-hidden">
            <table className="w-full table-fixed border-collapse text-[13px]">
              <thead>
                <tr>
                  {[
                    { h: "#", w: "w-10" },
                    { h: "Compound" },
                    { h: "Predicted pIC50", w: "w-28" },
                    { h: "AD z", w: "w-16" },
                    { h: "Confidence", w: "w-40" },
                  ].map((c) => (
                    <th key={c.h} className={`sticky top-0 z-10 border-b border-line bg-surface2 px-2.5 py-2.5 text-left text-[10.5px] font-semibold uppercase tracking-wide text-inkmut ${c.w || ""}`}>
                      {c.h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {d.in_domain.map((r, i) => (
                  <tr key={i} className="hover:bg-canvas">
                    <td className="border-b border-surface2 px-2.5 py-2.5">{r.rank}</td>
                    <td className="smi-mono border-b border-surface2 px-2.5 py-2.5">{r.smiles}</td>
                    <td className="border-b border-surface2 px-2.5 py-2.5 font-semibold">{r.predicted_pIC50 ?? "—"}</td>
                    <td className="border-b border-surface2 px-2.5 py-2.5 text-inkmut">{r.ad_z ?? "—"}</td>
                    <td className="border-b border-surface2 px-2.5 py-2.5">
                      <span className="chip min-w-0 max-w-full" title={r.confidence_label}>
                        <ConfidenceDot level={r.confidence} />
                        <span className="min-w-0 truncate">{r.confidence_label}</span>
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="flex items-center justify-between border-t border-line px-5 py-2.5">
            <span className="text-[12.5px] text-inkmut">
              {c.out_of_domain} out-of-domain · {c.skipped} skipped
            </span>
            <button className="btn-link" onClick={() => downloadCsv(toCsv(d), `${d.target.id || "predict"}_ranked.csv`)}>
              Download CSV
            </button>
          </div>
        </>
      ) : (
        <div className="px-8 py-16 text-center text-inkmut">No molecules fell inside this model's domain.</div>
      )}
    </div>
  );
}
