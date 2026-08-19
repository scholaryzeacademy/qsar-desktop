import { useCallback, useEffect, useRef, useState } from "react";
import * as api from "./api";
import type {
  AdvancedDockingBody,
  BindingSiteResponse,
  PocketResidue,
  ReceptorProfile,
  StructureCandidate,
} from "./types";

export type DockingMode = "site_specific" | "blind";

export interface SiteState {
  center?: [number, number, number];
  box_size?: [number, number, number];
  residues: PocketResidue[];
  blind_center?: [number, number, number];
  blind_box_size?: [number, number, number];
  receptorUrl: string | null;
  ligandUrl: string | null;
}

export const isGeneOnly = (targetId: string) => targetId.startsWith("GENE_");
export const residueKey = (r: PocketResidue) => `${r.chain}:${r.resnum}`;

/** Mirrors the original static/index.html's per-group `_advState[g]` blob —
    one instance per "Screen" / "Docking" tab, driven by that tab's current
    target selection. Owns binding-site evidence, the manual structure
    picker, residue-driven / drag-driven box overrides, and the
    exhaustiveness/poses/GNINA knobs — everything that feeds
    getAdvanced() -> AdvancedDocking on submit. */
export function useAdvancedDocking(targetId: string) {
  const [dockingMode, setDockingMode] = useState<DockingMode>("site_specific");
  const [site, setSite] = useState<SiteState | null>(null);
  const [siteError, setSiteError] = useState<string | null>(null);
  const [customProfile, setCustomProfile] = useState<ReceptorProfile | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [boxOverride, setBoxOverride] = useState<{ center: [number, number, number]; size: [number, number, number] } | null>(null);

  const [exhaustiveness, setExhaustiveness] = useState<string>("");
  const [nPoses, setNPoses] = useState<string>("");
  const [useGnina, setUseGnina] = useState(true);

  const [candidates, setCandidates] = useState<StructureCandidate[] | null>(null);
  const [candidatesLoading, setCandidatesLoading] = useState(false);
  const [pickedPdb, setPickedPdb] = useState<string | null>(null);
  const [structureStatus, setStructureStatus] = useState<{ kind: "muted" | "ok" | "warn" | "err"; text: string } | null>(null);
  const [preparingStructure, setPreparingStructure] = useState(false);

  const [autoValidateBusy, setAutoValidateBusy] = useState(false);
  const [autoValidateStatus, setAutoValidateStatus] = useState<{ kind: "muted" | "ok" | "err"; text: string } | null>(null);

  const residueTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const applyResidueSelection = useCallback(
    async (sel: Set<string>, siteVal: SiteState | null, profile: ReceptorProfile | null) => {
      if (!siteVal) return;
      const residues = (siteVal.residues || []).filter((r) => sel.has(residueKey(r)));
      if (!residues.length) {
        setBoxOverride(null);
        return;
      }
      try {
        const body: any = {
          target_id: targetId,
          residues: residues.map((r) => ({ chain: r.chain, resnum: r.resnum })),
          padding: 8.0,
        };
        if (profile?.receptor_pdb) body.receptor_pdb = profile.receptor_pdb;
        const r = await api.boxFromResidues(body);
        setBoxOverride({ center: r.center, size: r.box_size });
      } catch {
        /* leave prior override in place — a transient failure here shouldn't
           disturb whatever box was already in effect */
      }
    },
    [targetId]
  );

  const toggleResidue = useCallback(
    (key: string, checked: boolean) => {
      setSelected((prev) => {
        const next = new Set(prev);
        if (checked) next.add(key);
        else next.delete(key);
        if (residueTimer.current) clearTimeout(residueTimer.current);
        residueTimer.current = setTimeout(() => applyResidueSelection(next, site, customProfile), 400);
        return next;
      });
    },
    [applyResidueSelection, site, customProfile]
  );

  const loadStructureCandidates = useCallback(async (tid: string) => {
    setCandidatesLoading(true);
    setCandidates(null);
    setStructureStatus(null);
    setPickedPdb(null);
    try {
      const d = await api.structureCandidates(tid);
      setCandidates(d.candidates || []);
    } catch {
      setCandidates([]);
    } finally {
      setCandidatesLoading(false);
    }
  }, []);

  const loadBindingSite = useCallback(async (tid: string) => {
    setSelected(new Set());
    setBoxOverride(null);
    setSiteError(null);
    if (!tid) {
      setSite(null);
      return;
    }
    try {
      const d: BindingSiteResponse = await api.bindingSite(tid);
      const s: SiteState = {
        center: d.center,
        box_size: d.box_size,
        residues: d.pocket_residues || [],
        blind_center: d.blind_center,
        blind_box_size: d.blind_box_size,
        receptorUrl: api.apiUrl(`/api/docking/receptor/${tid}`),
        ligandUrl: d.has_reference_ligand_mol ? api.apiUrl(`/api/targets/${tid}/reference_ligand.sdf`) : null,
      };
      setSite(s);
      setSelected(new Set(s.residues.map(residueKey)));
    } catch {
      setSite(null);
      if (!isGeneOnly(tid)) setSiteError("No binding-site evidence for this target.");
    }
  }, []);

  // reset + reload whenever the owning tab's target selection changes
  useEffect(() => {
    setCustomProfile(null);
    setExhaustiveness("");
    setNPoses("");
    setUseGnina(true);
    if (!targetId) {
      setSite(null);
      setCandidates(null);
      return;
    }
    loadBindingSite(targetId);
    loadStructureCandidates(targetId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [targetId]);

  const applyBindingSiteFromProfile = useCallback((profile: ReceptorProfile) => {
    const s: SiteState = {
      center: profile.center,
      box_size: profile.box_size,
      residues: profile.binding_site_residues || [],
      blind_center: profile.blind_center,
      blind_box_size: profile.blind_box_size,
      receptorUrl: api.apiUrl(`/api/docking/receptor_file?path=${encodeURIComponent(profile.receptor_pdb)}`),
      ligandUrl: null,
    };
    setSite(s);
    setSelected(new Set(s.residues.map(residueKey)));
    setBoxOverride(null);
  }, []);

  const pickStructure = useCallback(
    async (pdbId: string, resname: string) => {
      setPickedPdb(pdbId);
      setBoxOverride(null);
      setSelected(new Set());
      setStructureStatus({ kind: "muted", text: `Preparing receptor for ${pdbId}… (strip/repair/PDBQT + a redocking check, ~1–2 min)` });
      setPreparingStructure(true);
      try {
        const sub = await api.submitCustomReceptor({ target_id: targetId, pdb_id: pdbId, ligand_resname: resname });
        while (true) {
          await api.sleep(3000);
          const j = await api.pollRetry(() => api.customReceptorJob(sub.job_id));
          if (j.status === "done" && j.profile) {
            setCustomProfile(j.profile);
            const p = j.profile;
            setStructureStatus(
              p.validated
                ? { kind: "ok", text: `Using ${pdbId} (manual) — redocking-validated (RMSD ${p.reference_rmsd} Å).` }
                : { kind: "warn", text: `Using ${pdbId} (manual) — NOT redocking-validated${p.redock_note ? ` (${p.redock_note})` : ""}; pose geometry is unconfirmed.` }
            );
            applyBindingSiteFromProfile(p);
            break;
          }
          if (j.status === "error") {
            setCustomProfile(null);
            setPickedPdb(null);
            setStructureStatus({ kind: "err", text: `Could not prepare ${pdbId}: ${j.error || "unknown error"}` });
            break;
          }
        }
      } catch (e: any) {
        setCustomProfile(null);
        setStructureStatus({ kind: "err", text: e.message || "Error" });
      } finally {
        setPreparingStructure(false);
      }
    },
    [targetId, applyBindingSiteFromProfile]
  );

  const runAutoValidate = useCallback(async () => {
    if (!targetId) {
      setAutoValidateStatus({ kind: "err", text: "Pick a target first." });
      return;
    }
    setAutoValidateBusy(true);
    setAutoValidateStatus({ kind: "muted", text: "Redocking ranked candidates in order, keeping the first that passes and is at least as good as any existing default — can take a few minutes." });
    try {
      const sub = await api.submitAutoValidate(targetId);
      let j;
      while (true) {
        await api.sleep(4000);
        j = await api.pollRetry(() => api.autoValidateJob(sub.job_id));
        if (j.status === "done" || j.status === "error") break;
      }
      if (j.status === "error") {
        setAutoValidateStatus({ kind: "err", text: j.error || "failed" });
        return;
      }
      const r = j.result!;
      if (!r.validated) {
        setAutoValidateStatus({
          kind: "muted",
          text: r.was_already_validated
            ? `No candidate matched or beat the existing default (${r.prior_pdb_source}, RMSD ${r.prior_reference_rmsd} Å) — kept as-is.`
            : `No candidate passed redocking validation (RMSD < 2 Å) for this target — still no automatic default. Pick a structure manually above, or use "Run Fresh Decoy Validation" per compound after docking.`,
        });
      } else if (r.changed) {
        setAutoValidateStatus({
          kind: "ok",
          text: r.was_already_validated
            ? `Found a better structure: ${r.pdb_source} (RMSD ${r.reference_rmsd} Å), replacing ${r.prior_pdb_source} (RMSD ${r.prior_reference_rmsd} Å). This is now the automatic default.`
            : `Found and set a new automatic default: ${r.pdb_source} (RMSD ${r.reference_rmsd} Å) — Automatic mode now works for this target without picking a manual structure.`,
        });
      } else {
        setAutoValidateStatus({ kind: "muted", text: `Already using the best validated structure (${r.pdb_source}, RMSD ${r.reference_rmsd} Å) — nothing changed.` });
      }
      loadBindingSite(targetId);
    } catch (e: any) {
      setAutoValidateStatus({ kind: "err", text: e.message || "Error" });
    } finally {
      setAutoValidateBusy(false);
    }
  }, [targetId, loadBindingSite]);

  const resetToAutomatic = useCallback(() => {
    setExhaustiveness("");
    setNPoses("");
    setUseGnina(true);
    setCustomProfile(null);
    setPickedPdb(null);
    setSelected(new Set(site ? site.residues.map(residueKey) : []));
    setBoxOverride(null);
    setStructureStatus(null);
    if (targetId) loadBindingSite(targetId);
  }, [targetId, site, loadBindingSite]);

  /** Whole-protein box in blind mode; else the box override (drag / residue
      selection) if present; else the automatic ligand-centered box. */
  const effectiveBox = useCallback((): [[number, number, number] | undefined, [number, number, number] | undefined] => {
    if (!site) return [undefined, undefined];
    if (dockingMode === "blind") return [site.blind_center || site.center, site.blind_box_size || site.box_size];
    if (boxOverride) return [boxOverride.center, boxOverride.size];
    return [site.center, site.box_size];
  }, [site, dockingMode, boxOverride]);

  const getAdvanced = useCallback((): AdvancedDockingBody | null => {
    const adv: AdvancedDockingBody = {};
    const exh = parseFloat(exhaustiveness);
    if (exhaustiveness !== "" && !isNaN(exh)) adv.exhaustiveness = Math.round(exh);
    const poses = parseFloat(nPoses);
    if (nPoses !== "" && !isNaN(poses)) adv.n_poses = Math.round(poses);
    if (!useGnina) adv.use_gnina = false;
    if (boxOverride) {
      adv.box_center = boxOverride.center;
      adv.box_size = boxOverride.size;
    }
    if (customProfile) adv.custom_profile = customProfile;
    if (dockingMode === "blind") adv.docking_mode = "blind";
    return Object.keys(adv).length ? adv : null;
  }, [exhaustiveness, nPoses, useGnina, boxOverride, customProfile, dockingMode]);

  return {
    targetId,
    dockingMode,
    setDockingMode,
    site,
    siteError,
    customProfile,
    selected,
    toggleResidue,
    boxOverride,
    setBoxOverride,
    exhaustiveness,
    setExhaustiveness,
    nPoses,
    setNPoses,
    useGnina,
    setUseGnina,
    candidates,
    candidatesLoading,
    pickedPdb,
    structureStatus,
    preparingStructure,
    pickStructure,
    autoValidateBusy,
    autoValidateStatus,
    runAutoValidate,
    resetToAutomatic,
    effectiveBox,
    getAdvanced,
    hasAutomaticDefault: !!site,
  };
}

export type AdvancedDockingState = ReturnType<typeof useAdvancedDocking>;
