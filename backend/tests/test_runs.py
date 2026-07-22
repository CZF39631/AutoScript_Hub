import os

FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


def _upload(client, token):
    path = os.path.join(FIXTURE_DIR, "sample_script.py")
    with open(path, "rb") as f:
        resp = client.post(
            "/api/scripts/upload",
            files={"file": ("s.py", f, "text/x-python")},
            data={"changelog": "test"},
            headers={"Authorization": f"Bearer {token}"},
        )
    return resp.json()["id"]


def test_execute_script(client, dev_token):
    sid = _upload(client, dev_token)
    resp = client.post(
        "/api/runs/execute",
        json={"script_id": sid, "params": {"url_file": "C:/test.txt"}},
        headers={"Authorization": f"Bearer {dev_token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "pending"
    assert data["script_id"] == sid


def test_execute_no_concurrent(client, dev_token):
    sid = _upload(client, dev_token)
    # Use valid params (url_file is required per sample_script config) so the request
    # passes validation and actually creates a run — otherwise we'd get 422 before
    # the concurrency check runs, defeating the test's purpose.
    client.post(
        "/api/runs/execute",
        json={"script_id": sid, "params": {"url_file": "C:/test.txt"}},
        headers={"Authorization": f"Bearer {dev_token}"},
    )
    resp = client.post(
        "/api/runs/execute",
        json={"script_id": sid, "params": {"url_file": "C:/test.txt"}},
        headers={"Authorization": f"Bearer {dev_token}"},
    )
    assert resp.status_code == 409


def test_list_runs(client, dev_token):
    sid = _upload(client, dev_token)
    client.post(
        "/api/runs/execute",
        json={"script_id": sid, "params": {"url_file": "C:/test.txt"}},
        headers={"Authorization": f"Bearer {dev_token}"},
    )
    resp = client.get("/api/runs", headers={"Authorization": f"Bearer {dev_token}"})
    assert resp.status_code == 200
    assert len(resp.json()) >= 1


def test_operator_sees_own_runs(client, op_token, dev_token):
    sid = _upload(client, dev_token)
    client.post(
        "/api/runs/execute",
        json={"script_id": sid, "params": {"url_file": "C:/test.txt"}},
        headers={"Authorization": f"Bearer {dev_token}"},
    )
    resp = client.get("/api/runs", headers={"Authorization": f"Bearer {op_token}"})
    assert resp.status_code == 200
    assert len(resp.json()) == 0


def test_cancel_run(client, dev_token):
    sid = _upload(client, dev_token)
    run_resp = client.post(
        "/api/runs/execute",
        json={"script_id": sid, "params": {"url_file": "C:/test.txt"}},
        headers={"Authorization": f"Bearer {dev_token}"},
    )
    rid = run_resp.json()["id"]
    resp = client.post(f"/api/runs/{rid}/cancel", headers={"Authorization": f"Bearer {dev_token}"})
    assert resp.status_code == 200


def test_update_run_status(client, dev_token):
    sid = _upload(client, dev_token)
    run_resp = client.post(
        "/api/runs/execute",
        json={"script_id": sid, "params": {"url_file": "C:/test.txt"}},
        headers={"Authorization": f"Bearer {dev_token}"},
    )
    rid = run_resp.json()["id"]
    resp = client.patch(
        f"/api/runs/{rid}/status",
        json={"status": "running"},
        headers={"Authorization": f"Bearer {dev_token}"},
    )
    assert resp.status_code == 200
    resp = client.patch(
        f"/api/runs/{rid}/status",
        json={"status": "success", "log_path": "storage/logs/1.log"},
        headers={"Authorization": f"Bearer {dev_token}"},
    )
    assert resp.status_code == 200
    detail = client.get(f"/api/runs/{rid}", headers={"Authorization": f"Bearer {dev_token}"})
    assert detail.json()["status"] == "success"
    assert detail.json()["duration_sec"] is not None
    assert detail.json()["log_path"] is None


def test_result_files_are_client_local_and_server_has_no_open_or_download_routes():
    from app.main import app

    paths = {route.path for route in app.routes}
    assert "/api/runs/{run_id}/open-result" not in paths
    assert "/api/runs/{run_id}/download" not in paths


def test_agent_claims_run_when_marking_it_running(client, dev_token):
    agent_resp = client.post(
        "/api/agents/register",
        json={"machine_name": "developer-pc", "agent_version": "1.0.0"},
        headers={"Authorization": f"Bearer {dev_token}"},
    )
    agent_id = agent_resp.json()["id"]
    sid = _upload(client, dev_token)
    run_resp = client.post(
        "/api/runs/execute",
        json={"script_id": sid, "params": {"url_file": "C:/test.txt"}},
        headers={"Authorization": f"Bearer {dev_token}"},
    )
    run_id = run_resp.json()["id"]

    updated = client.patch(
        f"/api/runs/{run_id}/status",
        json={"status": "running", "agent_id": agent_id},
        headers={"Authorization": f"Bearer {dev_token}"},
    )
    detail = client.get(
        f"/api/runs/{run_id}",
        headers={"Authorization": f"Bearer {dev_token}"},
    )

    assert updated.status_code == 200
    assert detail.json()["agent_id"] == agent_id
