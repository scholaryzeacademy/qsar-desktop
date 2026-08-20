"""downloads.py: manifest-driven download/extract, without touching real S3."""
import hashlib
import io
import time
import zipfile

import pytest

import downloads as D


class _FakeManifestResponse:
    def __init__(self, data):
        self._data = data
    def raise_for_status(self):
        pass
    def json(self):
        return self._data


class _FakeStreamResponse:
    def __init__(self, content, headers=None):
        self._content = content
        self.headers = headers or {}
    def raise_for_status(self):
        pass
    def iter_bytes(self, chunk_size=1024 * 1024):
        for i in range(0, len(self._content), chunk_size):
            yield self._content[i:i + chunk_size]


class _FakeStreamCtx:
    def __init__(self, resp):
        self._resp = resp
    def __enter__(self):
        return self._resp
    def __exit__(self, *a):
        return False


def _zip_bytes(target_id, files):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for relpath, content in files.items():
            z.writestr(f"{target_id}/{relpath}", content)
    return buf.getvalue()


def _poll(client, job_id, tries=50):
    p = {}
    for _ in range(tries):
        p = client.get(f"/api/downloads/progress/{job_id}").json()
        if p["state"] in ("done", "error"):
            break
        time.sleep(0.05)
    return p


@pytest.fixture
def isolated_dirs(tmp_path, monkeypatch):
    models_dir = tmp_path / "models"
    docking_dir = tmp_path / "docking_targets"
    monkeypatch.setattr(D.MA, "TARGETS_DIR", str(models_dir))
    monkeypatch.setattr(D, "DOCKING_TARGETS_DIR", str(docking_dir))
    return models_dir, docking_dir


def test_status_disabled_without_download_base_url(client, monkeypatch):
    monkeypatch.setattr(D, "DOWNLOAD_BASE_URL", "")
    r = client.get("/api/downloads/status")
    assert r.status_code == 503


def test_download_happy_path(client, monkeypatch, isolated_dirs):
    models_dir, _ = isolated_dirs
    monkeypatch.setattr(D, "DOWNLOAD_BASE_URL", "http://fake")
    monkeypatch.setattr(D, "_manifest_cache", {"data": None, "fetched_at": 0.0})
    zb = _zip_bytes("FAKE_T1", {
        "chosen_model/predictor.pkl": b"x",
        "selected_features.csv": b"f1,f2\n",
        "Data/fit.csv": b"f1,f2\n1,2\n",
        "note.txt": b"hello",
    })
    sha = hashlib.sha256(zb).hexdigest()
    manifest = {"targets": {"FAKE_T1": {"qsar_model": {"size": len(zb), "sha256": sha}, "docking": None}}}

    monkeypatch.setattr(D.httpx, "get", lambda url, timeout=15: _FakeManifestResponse(manifest))
    monkeypatch.setattr(
        D.httpx, "stream",
        lambda method, url, timeout=60: _FakeStreamCtx(
            _FakeStreamResponse(zb, headers={"content-length": str(len(zb))})
        ),
    )

    r = client.get("/api/downloads/status")
    assert r.status_code == 200
    row = next(t for t in r.json()["targets"] if t["target_id"] == "FAKE_T1")
    assert row["model"] == {"available": True, "size": len(zb), "installed": False}

    r = client.post("/api/downloads/target/FAKE_T1", params={"kind": "model"})
    assert r.status_code == 200
    job_id = r.json()["job_id"]
    assert job_id

    p = _poll(client, job_id)
    assert p["state"] == "done", p
    assert (models_dir / "FAKE_T1" / "note.txt").read_bytes() == b"hello"
    assert not (models_dir / "FAKE_T1.tmp").exists()

    row = next(t for t in client.get("/api/downloads/status").json()["targets"] if t["target_id"] == "FAKE_T1")
    assert row["model"]["installed"] is True

    # already installed -> no-op, no new job
    r = client.post("/api/downloads/target/FAKE_T1", params={"kind": "model"})
    assert r.json() == {"job_id": None, "already_installed": True}


def test_checksum_mismatch_rejected(client, monkeypatch, isolated_dirs):
    monkeypatch.setattr(D, "DOWNLOAD_BASE_URL", "http://fake")
    monkeypatch.setattr(D, "_manifest_cache", {"data": None, "fetched_at": 0.0})
    zb = _zip_bytes("FAKE_T2", {"a.txt": b"1"})
    manifest = {"targets": {"FAKE_T2": {"qsar_model": {"size": len(zb), "sha256": "0" * 64}, "docking": None}}}
    monkeypatch.setattr(D.httpx, "get", lambda url, timeout=15: _FakeManifestResponse(manifest))
    monkeypatch.setattr(
        D.httpx, "stream",
        lambda method, url, timeout=60: _FakeStreamCtx(_FakeStreamResponse(zb)),
    )

    job_id = client.post("/api/downloads/target/FAKE_T2", params={"kind": "model"}).json()["job_id"]
    p = _poll(client, job_id)
    assert p["state"] == "error"
    assert "checksum" in p["error"]


def test_extract_rejects_path_traversal(tmp_path, isolated_dirs):
    models_dir, _ = isolated_dirs
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("FAKE_T3/../../evil.txt", b"pwned")
        z.writestr("FAKE_T3/ok.txt", b"fine")
    zip_path = tmp_path / "in.zip"
    zip_path.write_bytes(buf.getvalue())

    D._extract_zip(str(zip_path), "FAKE_T3", str(models_dir))

    assert (models_dir / "FAKE_T3" / "ok.txt").read_bytes() == b"fine"
    assert list(tmp_path.rglob("evil.txt")) == []
