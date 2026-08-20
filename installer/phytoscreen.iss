; PhytoScreen Windows installer (Inno Setup 6).
; Built by .github/workflows/build-windows.yml on a windows-latest runner
; from the PyInstaller onedir output (dist\PhytoScreen\); not meant to be
; run by hand except to sanity-check the packaging (see BUILD_WINDOWS.md).
;
; Ships without models/ or docking_targets/ (~101GB / 2.3GB) — those are
; pulled on demand by the Downloads tab (backend/downloads.py) from
; whatever PhytoScreen.bat's DOWNLOAD_BASE_URL points at.

#define MyAppName "PhytoScreen"
#ifndef MyAppVersion
  #define MyAppVersion "0.0.0-dev"
#endif
#define MyAppExeName "PhytoScreen.bat"

[Setup]
AppId={{B6E2B9A0-6E6D-4C2D-9E3E-8B7B7B7C1A11}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputBaseFilename=PhytoScreenSetup
OutputDir=dist_installer
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
; models/docking_targets are downloaded post-install (Downloads tab), not
; carried by this installer — this is a real requirement, not a nicety:
; the onedir PyInstaller output can still be sizeable (torch/rdkit/
; autogluon/chemprop wheels), so don't assume "small enough for LZMA to
; not matter."

[Files]
Source: "..\dist\PhytoScreen\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion
Source: "PhytoScreen.bat"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional shortcuts:"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent
