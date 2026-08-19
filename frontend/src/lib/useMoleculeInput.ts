import { useCallback, useState } from "react";
import { parseSdf } from "./api";

export type InputMode = "paste" | "csv" | "sdf";

export interface MoleculeInputState {
  mode: InputMode;
  setMode: (m: InputMode) => void;
  pasteText: string;
  setPasteText: (v: string) => void;
  csvFile: File | null;
  setCsvFile: (f: File | null) => void;
  sdfFile: File | null;
  setSdfFile: (f: File | null) => void;
  resolve: () => Promise<string[]>;
}

async function csvToSmiles(file: File): Promise<string[]> {
  const lines = (await file.text()).split(/\r?\n/).filter((x) => x.trim());
  if (!lines.length) return [];
  let idx = 0;
  let start = 0;
  const head = lines[0].split(",").map((s) => s.trim().replace(/^"|"$/g, ""));
  const si = head.findIndex((h) => h.toLowerCase() === "smiles");
  if (si >= 0) {
    idx = si;
    start = 1;
  }
  return lines
    .slice(start)
    .map((l) => (l.split(",")[idx] || "").trim().replace(/^"|"$/g, ""))
    .filter(Boolean);
}

export function useMoleculeInput(): MoleculeInputState {
  const [mode, setMode] = useState<InputMode>("paste");
  const [pasteText, setPasteText] = useState("");
  const [csvFile, setCsvFile] = useState<File | null>(null);
  const [sdfFile, setSdfFile] = useState<File | null>(null);

  const resolve = useCallback(async () => {
    if (mode === "csv") {
      if (!csvFile) throw new Error("Choose a CSV file.");
      return csvToSmiles(csvFile);
    }
    if (mode === "sdf") {
      if (!sdfFile) throw new Error("Choose an SDF file.");
      const d = await parseSdf(sdfFile);
      return d.smiles;
    }
    return pasteText
      .split(/\r?\n/)
      .map((s) => s.trim())
      .filter(Boolean);
  }, [mode, pasteText, csvFile, sdfFile]);

  return { mode, setMode, pasteText, setPasteText, csvFile, setCsvFile, sdfFile, setSdfFile, resolve };
}
