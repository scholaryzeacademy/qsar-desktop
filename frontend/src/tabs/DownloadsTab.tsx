import { useEffect, useMemo, useRef, useState } from "react";
import * as api from "../lib/api";
import { useAppData } from "../lib/AppDataContext";
import { SectionIntro } from "../components/Shell";
import { Badge, EmptyState, ErrorBox, Notice, Spinner } from "../components/Feedback";
import { fmtBytes } from "../lib/format";
import type { DownloadTargetRow } from "../lib/types";

type Kind = "model" | "docking";

interface JobState {
  state: string;
  done: number;
  total: number;
  error?: string | null;
  jobId?: string | null;
}

export function DownloadsTab() {
  const { refresh } = useAppData();
  const [state, setState] = useState<"loading" | "disabled" | "error" | "done">("loading");
  const [error, setError] = useState("");
  const [rows, setRows] = useState<DownloadTargetRow[]>([]);
  const [query, setQuery] = useState("");
  const [jobs, setJobs] = useState<Record<string, JobState>>({});
  const activeRef = useRef<Set<string>>(new Set());

  const loadStatus = async () => {
    try {
      const s = await api.downloadsStatus();
      setRows(s.targets);
      setState("done");
    } catch (e: any) {
      if (String(e.message || "").includes("DOWNLOAD_BASE_URL")) {
        setState("disabled");
      } else {
        setError(e.message || "Error");
        setState("error");
      }
    }
  };

  useEffect(() => {
    loadStatus();
  }, []);

  const key = (targetId: string, kind: Kind) => `${targetId}:${kind}`;

  const startDownload = async (targetId: string, kind: Kind) => {
    const jobKey = key(targetId, kind);
    if (activeRef.current.has(jobKey)) return;
    activeRef.current.add(jobKey);
    setJobs((j) => ({ ...j, [jobKey]: { state: "starting", done: 0, total: 0, error: null } }));
    try {
      await api.ensureDownloaded(
        targetId,
        kind,
        (p) => setJobs((j) => ({ ...j, [jobKey]: { ...j[jobKey], state: p.state, done: p.done, total: p.total, error: p.error } })),
        (jobId) => setJobs((j) => ({ ...j, [jobKey]: { ...j[jobKey], jobId } }))
      );
      setJobs((j) => {
        const { [jobKey]: _drop, ...rest } = j;
        return rest;
      });
      await loadStatus();
      refresh();
    } catch (e: any) {
      setJobs((j) => ({ ...j, [jobKey]: { state: "error", done: 0, total: 0, error: e.message || "Error" } }));
    } finally {
      activeRef.current.delete(jobKey);
    }
  };

  const stopDownload = async (targetId: string, kind: Kind) => {
    const jobId = jobs[key(targetId, kind)]?.jobId;
    if (!jobId) return;
    try {
      await api.cancelDownload(jobId);
    } catch {
      /* the poll loop will still surface a final status either way */
    }
  };

  const filtered = useMemo(
    () => rows.filter((r) => r.target_id.toLowerCase().includes(query.toLowerCase())),
    [rows, query]
  );

  const installedCount = rows.filter((r) => r.model.installed || r.docking.installed).length;

  return (
    <div className="card min-h-[60vh] overflow-hidden">
      <div className="p-5 pb-0">
        <SectionIntro
          title="Downloads"
          sub="This install ships without target data — pull only the buckets you need, on demand. Model buckets can be hundreds of MB to a few GB each; docking buckets are typically a few MB."
        />
      </div>

      {state === "loading" && <Spinner />}
      {state === "error" && (
        <div className="p-5 pt-0">
          <ErrorBox message={error} />
        </div>
      )}
      {state === "disabled" && (
        <div className="p-5 pt-0">
          <Notice>
            No download source is configured for this build (DOWNLOAD_BASE_URL is unset). Set it as an environment
            variable before launching, or copy target buckets into <code>models/</code>/<code>docking_targets/</code>{" "}
            manually.
          </Notice>
        </div>
      )}
      {state === "done" && (
        <>
          <div className="flex items-center justify-between gap-3 px-5 py-3">
            <input
              className="field-input max-w-xs"
              placeholder="Search targets…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
            <div className="text-[12px] text-inkmut">
              <b className="text-ink">{installedCount}</b> / {rows.length} targets have data installed
            </div>
          </div>
          {!filtered.length ? (
            <EmptyState title="No targets found" hint="Try a different search term." />
          ) : (
            <div className="overflow-x-auto px-5 pb-5">
              <table className="w-full border-collapse text-[12.5px]">
                <thead>
                  <tr className="border-b border-line text-left text-[10.5px] font-semibold uppercase tracking-wide text-inkmut">
                    <th className="py-2 pr-3">Target</th>
                    <th className="py-2 pr-3">QSAR model</th>
                    <th className="py-2 pr-3">Docking receptor</th>
                  </tr>
                </thead>
                <tbody>
                  {filtered.map((row) => (
                    <tr key={row.target_id} className="border-b border-line/60">
                      <td className="py-2 pr-3 font-mono text-[12px]">{row.target_id}</td>
                      <DownloadCell
                        status={row.model}
                        job={jobs[key(row.target_id, "model")]}
                        onDownload={() => startDownload(row.target_id, "model")}
                        onStop={() => stopDownload(row.target_id, "model")}
                      />
                      <DownloadCell
                        status={row.docking}
                        job={jobs[key(row.target_id, "docking")]}
                        onDownload={() => startDownload(row.target_id, "docking")}
                        onStop={() => stopDownload(row.target_id, "docking")}
                      />
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </div>
  );
}

function DownloadCell({
  status,
  job,
  onDownload,
  onStop,
}: {
  status: { available: boolean; installed: boolean; size?: number };
  job?: JobState;
  onDownload: () => void;
  onStop: () => void;
}) {
  if (!status.available) {
    return <td className="py-2 pr-3 text-inkmut">—</td>;
  }
  if (status.installed) {
    return (
      <td className="py-2 pr-3">
        <Badge ok>Installed</Badge>
      </td>
    );
  }
  if (job && (job.state === "starting" || job.state === "downloading" || job.state === "extracting")) {
    const pct = job.total ? Math.round((100 * job.done) / job.total) : 0;
    return (
      <td className="py-2 pr-3">
        <div className="w-40">
          <div className="h-1.5 overflow-hidden rounded-full bg-surface2">
            <div className="h-full rounded-full bg-brand-500 transition-all duration-300" style={{ width: `${pct}%` }} />
          </div>
          <div className="mt-0.5 flex items-center gap-1.5 text-[10.5px] text-inkmut">
            <span>{job.state === "extracting" ? "Extracting…" : `${pct}% of ${fmtBytes(job.total)}`}</span>
            {job.jobId && (
              <button type="button" className="text-brand-700 underline" onClick={onStop}>
                Stop
              </button>
            )}
          </div>
        </div>
      </td>
    );
  }
  if (job?.state === "error") {
    return (
      <td className="py-2 pr-3">
        <button className="btn-link text-clay" onClick={onDownload} title={job.error || "Error"}>
          Retry download
        </button>
      </td>
    );
  }
  return (
    <td className="py-2 pr-3">
      <button className="btn-link" onClick={onDownload}>
        Download{status.size ? ` (${fmtBytes(status.size)})` : ""}
      </button>
    </td>
  );
}
