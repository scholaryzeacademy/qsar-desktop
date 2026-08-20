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

  The ADMET-AI worker (backend/admet_service.py) is optional and started
  separately exactly as before; the desktop app talks to it over the same
  local URL (ADMET_SERVICE_URL, see backend/admet.py).

  --windowed (no console) means print()/stderr go nowhere a user can
  ever see — a startup failure used to just look like "nothing happens."
  Everything below also writes to a persistent log file
  (%LOCALAPPDATA%\\PhytoScreen\\desktop.log on Windows) and, on a truly
  fatal failure, pops a native message box pointing at it — see _log()/
  _fatal() below.
============================================================
"""
import os, sys, threading, socket, time, contextlib, traceback, datetime

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
        uvicorn.run(app, host=HOST, port=port, log_level="warning")
    except Exception:
        # Runs in a daemon thread — an uncaught exception here is normally
        # invisible (default threading.excepthook prints to a stderr that
        # --windowed has already thrown away, then the thread just dies).
        # Record it so main()'s _wait_up() timeout can report the REAL
        # cause instead of a generic "backend failed to start."
        _server_error.append(traceback.format_exc())
        _log(f"[desktop] backend thread crashed:\n{_server_error[-1]}")


def main():
    # working directory drives where models/, docking_targets/,
    # docking_registry.json resolve (see backend/serving/model_adapter.py,
    # backend/docking/profile.py) — default it to the exe's own folder
    # when frozen, so a double-clicked PhytoScreen.exe works from any cwd.
    if getattr(sys, "frozen", False):
        os.chdir(os.path.dirname(sys.executable))

    _log(f"[desktop] starting (frozen={getattr(sys, 'frozen', False)}, cwd={os.getcwd()})")
    _put_bundled_binaries_on_path()

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
