"""
============================================================
  PhytoScreen DESKTOP  (desktop.py)
============================================================
  Wraps the existing FastAPI JSON API (backend/app.py, unchanged) in a
  native desktop window (no browser, no manual localhost, no separate
  frontend dev server) by mounting the built frontend (frontend/dist/)
  onto the same app instance, added last so it never shadows /api/*.

  This is the ONLY place that knows about frontend/dist/ — backend/app.py
  stays a pure JSON API for anyone still running it directly with
  `uvicorn app:app --app-dir backend` (see README.md).

  Run (dev):   python desktop.py        (needs `npm run build` in
                                          frontend/ first, or set
                                          PHYTO_SKIP_STATIC=1 to run
                                          API-only and open the Vite dev
                                          server separately)
  Build .exe:  see BUILD_WINDOWS.md  (PyInstaller — note the mandatory
                                       --paths backend flag: PyInstaller
                                       only bundles what it can see via
                                       static import analysis, and it
                                       can't see `import app` below
                                       resolving to backend/app.py unless
                                       told where to look at BUILD time,
                                       same as this file tells Python
                                       where to look at RUN time)

  The ADMET-AI worker (backend/admet_service.py) is a separate process
  for the split web deployment, started by hand — nobody does that for a
  double-clicked desktop app, so this file starts it itself, in its own
  background thread on its own port (see start_admet_worker() below),
  giving full ADMET endpoint parity with a "both processes running" web
  deployment automatically. Set ADMET_SERVICE_URL yourself before
  launching to point at a real separately-run worker instead (e.g. a
  shared one) — this file leaves that alone rather than overriding it.

  --windowed (no console) means print()/stderr go nowhere a user can
  ever see — a startup failure used to just look like "nothing happens."
  Everything below also writes to a persistent log file
  (%LOCALAPPDATA%\\PhytoScreen\\desktop.log on Windows) and, on a truly
  fatal failure, pops a native message box pointing at it — see _log()/
  _fatal() below.
============================================================
"""
import os, sys, threading, socket, time, contextlib, traceback, datetime

# A --windowed PyInstaller build has NO console at all on Windows —
# sys.stdout/sys.stderr are None, not just redirected/closed. print()
# specifically special-cases this and silently no-ops (documented CPython
# behavior for exactly this GUI-subsystem scenario), but plenty of library
# code doesn't: it pokes sys.stdout/stderr directly (.isatty(), .write(),
# .fileno(), ...) and crashes with AttributeError the instant it runs.
# Found via uvicorn's own colorized-logging formatter, which calls
# sys.stdout.isatty() during Config.__init__ — caught by the Windows CI
# step that actually launches the built exe (see build-windows.yml) before
# this ever reached a real user a second time. Give every library a real,
# harmless writable stream instead of None, as early as possible (module
# import time, before anything else runs).
if sys.stdout is None or sys.stderr is None:
    _null = open(os.devnull, "w")
    sys.stdout = sys.stdout or _null
    sys.stderr = sys.stderr or _null

HOST = "127.0.0.1"
REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
FROZEN_ROOT = getattr(sys, "_MEIPASS", REPO_ROOT)
BACKEND_DIR = os.path.join(REPO_ROOT, "backend")
FRONTEND_DIST = os.path.join(FROZEN_ROOT, "frontend", "dist")
BIN_DIR = os.path.join(FROZEN_ROOT, "bin")


def _log_dir():
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        return os.path.join(base, "PhytoScreen")
    return REPO_ROOT


LOG_PATH = os.path.join(_log_dir(), "desktop.log")


def _log(msg):
    """Never let logging itself crash the app — best-effort only."""
    try:
        os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"{datetime.datetime.now().isoformat(timespec='seconds')} {msg}\n")
    except Exception:
        pass
    print(msg)


def _fatal(msg):
    """A hard failure with no fallback UI to show instead (unlike the
       pywebview-unavailable case below, which still has a working
       server + printed URL) — pop a native message box so a --windowed
       build (no console) doesn't just silently do nothing."""
    _log(f"[desktop] FATAL: {msg}")
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(
                0,
                f"PhytoScreen failed to start:\n\n{msg}\n\nDetails were written to:\n{LOG_PATH}",
                "PhytoScreen — startup error",
                0x10,  # MB_ICONERROR
            )
        except Exception:
            pass
    sys.exit(1)


def _free_port():
    with contextlib.closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
        s.bind((HOST, 0))
        return s.getsockname()[1]


def _wait_up(port, timeout=30):
    import urllib.request
    end = time.time() + timeout
    while time.time() < end:
        try:
            urllib.request.urlopen(f"http://{HOST}:{port}/api/health", timeout=1)
            return True
        except Exception:
            time.sleep(0.25)
    return False


def _put_bundled_binaries_on_path():
    """Docking engines (backend/docking/engines.py, availability.py) find
       vina/fpocket/gnina via shutil.which() — bundling them in bin/ and
       prepending it to PATH here means that code needs zero changes."""
    if os.path.isdir(BIN_DIR):
        os.environ["PATH"] = BIN_DIR + os.pathsep + os.environ.get("PATH", "")


def build_app():
    """Import the existing serving app (backend/app.py, unchanged) and,
       unless skipped, mount the built frontend onto it. Working directory
       stays the repo root (or the frozen exe's own folder) so models/,
       docking_targets/, docking_registry.json resolve exactly as they do
       for the split web deployment (see README.md's --app-dir note).

       BACKEND_DIR only matters in dev mode (unfrozen) — when frozen,
       `import app` resolves through PyInstaller's own bundled-module
       finder instead, populated by --paths backend at build time (see
       BUILD_WINDOWS.md); this sys.path entry is harmless dead weight
       in that case, not load-bearing."""
    if BACKEND_DIR not in sys.path:
        sys.path.insert(0, BACKEND_DIR)
    import app as serving          # backend/app.py (unchanged)

    if not os.environ.get("PHYTO_SKIP_STATIC"):
        if os.path.isdir(FRONTEND_DIST):
            from fastapi.staticfiles import StaticFiles
            serving.app.mount(
                "/", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend"
            )
        else:
            _log(f"[desktop] no built frontend at {FRONTEND_DIST} "
                 f"(run `npm run build` in frontend/, or set PHYTO_SKIP_STATIC=1 "
                 f"and open the Vite dev server separately) — API-only for now.")
    return serving.app


_server_error = []  # [] = still starting/ok, [exc_text] = the thread died


def start_server(port):
    try:
        import uvicorn
        app = build_app()
        _log(f"[desktop] backend built OK, starting uvicorn on port {port}")
        # log_config=None: skip uvicorn's own logging setup entirely — its
        # colorized console formatter is what crashed on sys.stdout=None
        # above, and we don't use console-visible uvicorn logs anyway
        # (desktop.log is this app's actual diagnostic trail).
        uvicorn.run(app, host=HOST, port=port, log_level="warning", log_config=None)
    except Exception:
        # Runs in a daemon thread — an uncaught exception here is normally
        # invisible (default threading.excepthook prints to a stderr that
        # --windowed has already thrown away, then the thread just dies).
        # Record it so main()'s _wait_up() timeout can report the REAL
        # cause instead of a generic "backend failed to start."
        _server_error.append(traceback.format_exc())
        _log(f"[desktop] backend thread crashed:\n{_server_error[-1]}")


def start_admet_worker(port):
    """The learned ADMET-AI layer (backend/admet_service.py) is normally a
       SEPARATE process the web deployment's operator starts by hand
       (see README.md) — nobody does that for a double-clicked desktop
       app, so without this, admet.py's health check against
       ADMET_SERVICE_URL always fails and the app silently falls back to
       deterministic-only results, looking like fewer ADMET endpoints
       than "the web version." Runs in its own background thread here
       instead, giving the same automatic parity with zero setup.

       This is a weaker isolation boundary than a real separate process
       (a hard crash — not just a Python exception — could in principle
       still affect this process), but admet.py's own health-check +
       graceful-degrade design (unavailable -> deterministic layer only)
       already covers the common failure mode (admet-ai missing/broken),
       and failure here must never be allowed to affect the main backend
       thread — hence the broad except below, unlike start_server()'s
       (whose failure IS fatal to the whole app)."""
    try:
        if BACKEND_DIR not in sys.path:
            sys.path.insert(0, BACKEND_DIR)
        import uvicorn
        import admet_service
        _log(f"[desktop] starting ADMET-AI worker on port {port}")
        uvicorn.run(admet_service.app, host=HOST, port=port, log_level="warning", log_config=None)
    except Exception:
        _log(f"[desktop] ADMET-AI worker failed to start (non-fatal — "
             f"the deterministic ADMET layer still works):\n{traceback.format_exc()}")


def main():
    # working directory drives where models/, docking_targets/ (USER data,
    # downloaded on demand — see downloads.py) resolve — default it to the
    # exe's own folder when frozen, so a double-clicked PhytoScreen.exe
    # works from any cwd and downloaded data lands somewhere a user would
    # actually find it, not buried inside PyInstaller's own _internal/.
    if getattr(sys, "frozen", False):
        os.chdir(os.path.dirname(sys.executable))

        # docking_registry.json and panel_results_v2.csv are READ-ONLY data
        # bundled INTO the app (via --add-data — see BUILD_WINDOWS.md) —
        # for a PyInstaller 6.x onedir build these land in _internal/
        # (== FROZEN_ROOT/sys._MEIPASS), which is NOT the same folder as
        # the exe itself (sys.executable's dirname, set as cwd just above).
        # Both backend/docking/profile.py's DOCKING_REGISTRY and
        # backend/scripts/panel_candidates.py's PANEL_RESULTS_CSV default
        # to a bare relative filename resolved against cwd — silently
        # finding nothing there (no error: os.path.exists() just returns
        # False, so the registry loads as {} and the disease/target panel
        # as empty) rather than the real bundled copy in _internal/. This
        # is why disease search and target validation badges showed
        # nothing in a real frozen build despite dev-mode testing (where
        # cwd == the repo root == where these files actually live)
        # working fine the whole time. Point both at FROZEN_ROOT
        # explicitly — must happen before build_app() ever imports
        # anything that reads them.
        os.environ.setdefault("DOCKING_REGISTRY", os.path.join(FROZEN_ROOT, "docking_registry.json"))
        os.environ.setdefault("PANEL_RESULTS_CSV", os.path.join(FROZEN_ROOT, "panel_results_v2.csv"))

    _log(f"[desktop] starting (frozen={getattr(sys, 'frozen', False)}, cwd={os.getcwd()})")
    _put_bundled_binaries_on_path()

    # Must happen BEFORE build_app() ever imports backend/app.py -> admet.py,
    # since admet.py reads ADMET_SERVICE_URL once, at import time — setting
    # it later would be a no-op. An explicit ADMET_SERVICE_URL already set
    # (e.g. pointing at a real separately-run worker) is left alone.
    if "ADMET_SERVICE_URL" not in os.environ:
        admet_port = _free_port()
        os.environ["ADMET_SERVICE_URL"] = f"http://{HOST}:{admet_port}"
        threading.Thread(target=start_admet_worker, args=(admet_port,), daemon=True).start()

    port = _free_port()
    threading.Thread(target=start_server, args=(port,), daemon=True).start()
    if not _wait_up(port):
        if _server_error:
            _fatal(f"the backend crashed on startup:\n\n{_server_error[-1]}")
        else:
            _fatal(f"the backend did not respond on port {port} within 30s "
                    f"(no crash was caught — it may be hanging on a slow import).")
    _log("[desktop] backend is up, serving")
    url = f"http://{HOST}:{port}/"
    try:
        import webview
        window = webview.create_window("PhytoScreen", url, width=1280, height=860, min_size=(1000, 700))
        webview.start()          # blocks until the window closes
        return
    except ImportError:
        _log(f"[desktop] pywebview not installed. Open {url} in a browser, or `pip install pywebview`.")
    except Exception as e:
        # pywebview IS installed but no usable GUI backend was found at
        # runtime (e.g. no GTK/Qt on this machine) -- this shouldn't happen
        # on a real Windows install (pywebview uses the built-in Edge
        # WebView2 backend there), but degrade to the same URL fallback
        # rather than crash if it ever does.
        _log(f"[desktop] could not open a native window ({e}). Open {url} in a browser instead.")
    # keep the server alive so the printed URL works
    while True:
        time.sleep(1)


if __name__ == "__main__":
    main()
