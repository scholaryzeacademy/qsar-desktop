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
  Build .exe:  see BUILD_WINDOWS.md  (PyInstaller)

  The ADMET-AI worker (backend/admet_service.py) is optional and started
  separately exactly as before; the desktop app talks to it over the same
  local URL (ADMET_SERVICE_URL, see backend/admet.py).
============================================================
"""
import os, sys, threading, socket, time, contextlib

HOST = "127.0.0.1"
REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.join(REPO_ROOT, "backend")
FRONTEND_DIST = os.path.join(
    getattr(sys, "_MEIPASS", REPO_ROOT), "frontend", "dist"
)
BIN_DIR = os.path.join(getattr(sys, "_MEIPASS", REPO_ROOT), "bin")


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
       for the split web deployment (see README.md's --app-dir note)."""
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
            print(f"[desktop] no built frontend at {FRONTEND_DIST} "
                  f"(run `npm run build` in frontend/, or set PHYTO_SKIP_STATIC=1 "
                  f"and open the Vite dev server separately) — API-only for now.")
    return serving.app


def start_server(port):
    import uvicorn
    app = build_app()
    uvicorn.run(app, host=HOST, port=port, log_level="warning")


def main():
    # working directory drives where models/, docking_targets/,
    # docking_registry.json resolve (see backend/serving/model_adapter.py,
    # backend/docking/profile.py) — default it to the exe's own folder
    # when frozen, so a double-clicked PhytoScreen.exe works from any cwd.
    if getattr(sys, "frozen", False):
        os.chdir(os.path.dirname(sys.executable))

    _put_bundled_binaries_on_path()

    port = _free_port()
    threading.Thread(target=start_server, args=(port,), daemon=True).start()
    if not _wait_up(port):
        print("[desktop] backend failed to start"); sys.exit(1)
    url = f"http://{HOST}:{port}/"
    try:
        import webview
        window = webview.create_window("PhytoScreen", url, width=1280, height=860, min_size=(1000, 700))
        webview.start()          # blocks until the window closes
        return
    except ImportError:
        print(f"[desktop] pywebview not installed. Open {url} in a browser, or `pip install pywebview`.")
    except Exception as e:
        # pywebview IS installed but no usable GUI backend was found at
        # runtime (e.g. no GTK/Qt on this machine) -- this shouldn't happen
        # on a real Windows install (pywebview uses the built-in Edge
        # WebView2 backend there), but degrade to the same URL fallback
        # rather than crash if it ever does.
        print(f"[desktop] could not open a native window ({e}). Open {url} in a browser instead.")
    # keep the server alive so the printed URL works
    while True:
        time.sleep(1)


if __name__ == "__main__":
    main()
