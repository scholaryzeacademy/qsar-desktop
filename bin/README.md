# bin/ — bundled Windows docking binaries

`desktop.py` prepends this directory to `PATH` at startup, so anything
here is found by `shutil.which()` in `backend/docking/engines.py` /
`availability.py` with zero code changes — same mechanism a normal
Windows install (Vina on `PATH` manually) already uses.

## vina.exe

AutoDock Vina 1.2.7, official Windows build, downloaded unmodified from:
https://github.com/ccsb-scripps/AutoDock-Vina/releases/download/v1.2.7/vina_1.2.7_win.exe
(Apache-2.0 license, per the AutoDock Vina project). `engines.py`'s
`VinaEngine` looks for a binary named exactly `vina` (`vina.exe` on
Windows), so don't rename this file.

To update: download the new `vina_<version>_win.exe` asset from
https://github.com/ccsb-scripps/AutoDock-Vina/releases and replace this
file (keep the `vina.exe` name).

## fpocket / gnina

Not bundled — neither publishes an official Windows build (both are
Linux/Mac-only tooling). Both already degrade gracefully when absent
(see `backend/docking/availability.py`, and `engines.py`'s
always-unavailable GNINA fallback) — the Docking tab reports exactly
what's missing rather than breaking. Revisit if a Windows build of
either ever surfaces.
