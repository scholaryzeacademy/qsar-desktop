"""End-to-end API tests against the real FastAPI app (CLAUDE.md §12): health,
targets, predict (in-domain and unparsable), ADMET worker-down fallback,
docking validation display, the Screen pipeline end-to-end, and the factory
bucket browser's path-traversal guard."""
import time


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    d = r.json()
    assert d["targets_in_bucket_dir"] >= 1
    assert "disclaimer" in d


def test_targets_lists_real_buckets(client):
    r = client.get("/api/targets")
    assert r.status_code == 200
    ids = [t["target_id"] for t in r.json()["targets"]]
    assert "CHEMBL1163125_BRD4" in ids


def test_predict_ranks_in_domain_and_skips_unparsable(client):
    r = client.post("/api/predict", json={
        "target_id": "CHEMBL1163125_BRD4",
        "smiles": ["CC(=O)Oc1ccccc1C(=O)O", "c1ccccc1", "bogus"],
    })
    assert r.status_code == 200
    d = r.json()
    assert d["counts"]["skipped"] == 1
    assert "bogus" in d["skipped"]
    assert d["counts"]["in_domain"] + d["counts"]["out_of_domain"] == 2
    for row in d["in_domain"]:
        assert row["predicted_pIC50"] is not None
        assert row["in_domain"] is True
    for row in d["out_of_domain"]:
        assert row["predicted_pIC50"] is None   # AD gate enforced at the API boundary


def test_predict_unknown_target_404s_not_crashes(client):
    r = client.post("/api/predict", json={"target_id": "no_such_target", "smiles": ["C"]})
    assert r.status_code in (404, 409)


def test_predict_empty_smiles_400s(client):
    r = client.post("/api/predict", json={"target_id": "CHEMBL1163125_BRD4", "smiles": []})
    assert r.status_code == 400


def test_admet_worker_down_falls_back_to_deterministic(client):
    """No ADMET-AI worker is running in this test environment — the
       deterministic layer must still return a full profile, never crash,
       and clearly say the learned layer is unavailable (CLAUDE.md §13)."""
    r = client.post("/api/admet", json={"target_id": "_", "smiles": ["CC(=O)Oc1ccccc1C(=O)O"]})
    assert r.status_code == 200
    d = r.json()
    assert d["mode"] == "result"
    p = d["profiles"][0]
    assert p["parsed_ok"] is True
    assert p["physicochemical"]["mw"] > 0
    assert p["learned"]["available"] is False
    assert "note" in p["learned"]


def test_docking_status_shows_cox2_validated_with_real_numbers(client):
    r = client.get("/api/docking/status")
    assert r.status_code == 200
    d = r.json()
    cox2 = next((t for t in d.get("target_details", []) if t["target_id"] == "cox2"), None)
    assert cox2 is not None
    assert cox2["validated"] is True
    assert cox2["reference_rmsd"] is not None and cox2["reference_rmsd"] < 2.0
    assert cox2["enrichment_auc"] is not None


def test_factory_bucket_download_blocks_path_traversal(client):
    r = client.get("/api/factory/download/CHEMBL1163125_BRD4", params={"path": "../../../etc/passwd"})
    assert r.status_code == 400


def test_factory_bucket_lists_real_annotated_files(client):
    r = client.get("/api/factory/bucket/CHEMBL1163125_BRD4")
    assert r.status_code == 200
    d = r.json()
    assert d["n_files"] > 0
    plot_files = [f for f in d["files"] if f["category"] == "Plots"]
    assert len(plot_files) == 9   # the 9 standard QSAR plots, CLAUDE.md §8
    assert all(f["annotation"] for f in plot_files)   # every known file is annotated


def test_screen_pipeline_end_to_end(client):
    r = client.post("/api/screen/submit", json={
        "target_id": "CHEMBL1163125_BRD4",
        "smiles": ["CC(=O)Oc1ccccc1C(=O)O", "bogus"],
    })
    assert r.status_code == 200
    jid = r.json()["job_id"]
    result = None
    for _ in range(60):
        s = client.get(f"/api/screen/job/{jid}").json()
        assert s["status"] in ("queued", "running", "done", "error")
        if s["status"] == "done":
            result = s["result"]; break
        if s["status"] == "error":
            raise AssertionError(f"screen job failed: {s.get('error')}")
        time.sleep(1)
    assert result is not None, "screen job did not finish in time"
    assert result["counts"]["skipped"] == 1
    assert len(result["shortlist"]) == 1
    assert result["shortlist"][0]["rank"] == 1
    assert "methods_note" in result

    csv = client.get(f"/api/screen/job/{jid}/export.csv")
    assert csv.status_code == 200
    assert "rank" in csv.text.splitlines()[0]
