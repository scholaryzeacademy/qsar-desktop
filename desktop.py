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
    """Import the serving app and attach the factory-bucket browser router."""
    # ensure the app's own folder is importable when frozen by PyInstaller
    here = os.path.dirname(os.path.abspath(__file__))
    if here not in sys.path:
        sys.path.insert(0, here)
    import app as serving          # the existing app.py (unchanged)
    try:
        import factory_browser
        serving.app.include_router(factory_browser.router)
    except Exception as e:
        print(f"[desktop] factory browser not mounted: {e}")
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
    except Exception:
        print(f"[desktop] pywebview not installed. Open {url} in a browser, or `pip install pywebview`.")
        # keep the server alive so the printed URL works
        while True:
            time.sleep(1)
    window = webview.create_window("PhytoScreen", url, width=1280, height=860, min_size=(1000, 700))
    webview.start()          # blocks until the window closes


if __name__ == "__main__":
    main()
