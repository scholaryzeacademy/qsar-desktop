"""
============================================================
  PhytoScreen DESKTOP  (desktop.py)
============================================================
  Wraps the existing FastAPI serving app in a native desktop window
  (no browser, no manual localhost). Reuses ALL existing features:
  Predict / ADMET / Compare / Docking / the validation panels, plus a
  new Models tab that browses the factory's per-target buckets and lets
  the researcher download any file (or the whole bucket as a zip).

  Run (dev):   python desktop.py
  Build .exe:  see BUILD_WINDOWS.md  (PyInstaller)

  The ADMET-AI worker (admet_service.py) is optional and started separately
  exactly as before; the desktop app talks to it over the same local URL.
============================================================
"""
import os, sys, threading, socket, time, contextlib

HOST = "127.0.0.1"


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


def build_app():
    """Import the serving app (factory_browser is mounted inside app.py itself)."""
    # ensure the app's own folder is importable when frozen by PyInstaller
    here = os.path.dirname(os.path.abspath(__file__))
    if here not in sys.path:
        sys.path.insert(0, here)
    import app as serving          # the existing app.py (unchanged)
    return serving.app


def start_server(port):
    import uvicorn
    app = build_app()
    uvicorn.run(app, host=HOST, port=port, log_level="warning")


def main():
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
        # pywebview IS installed but no usable GUI backend was found at runtime
        # (e.g. no GTK/Qt on this machine) -- this shouldn't happen on a real
        # Windows install (pywebview uses the built-in Edge WebView2 backend
        # there), but degrade to the same URL fallback rather than crash if
        # it ever does, per CLAUDE.md: a missing optional piece must never
        # take down the app.
        print(f"[desktop] could not open a native window ({e}). Open {url} in a browser instead.")
    # keep the server alive so the printed URL works
    while True:
        time.sleep(1)


if __name__ == "__main__":
    main()
