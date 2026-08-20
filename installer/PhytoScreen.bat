@echo off
rem Launcher installed next to PhytoScreen.exe (see phytoscreen.iss) — sets
rem DOWNLOAD_BASE_URL so the Downloads tab knows where to pull target
rem buckets from (see BUILD_WINDOWS.md / backend/downloads.py), then starts
rem the app. __DOWNLOAD_BASE_URL__ is substituted at CI build time (see
rem .github/workflows/build-windows.yml) from the DOWNLOAD_BASE_URL repo
rem variable — edit this file after install to point at a different bucket
rem without needing a rebuild.
set DOWNLOAD_BASE_URL=__DOWNLOAD_BASE_URL__
start "" "%~dp0PhytoScreen.exe"
