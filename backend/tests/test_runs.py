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
    client.post(
        "/api/runs/execute",
        json={"script_id": sid, "params": {}},
        headers={"Authorization": f"Bearer {dev_token}"},
    )
    resp = client.post(
        "/api/runs/execute",
        json={"script_id": sid, "params": {}},
        headers={"Authorization": f"Bearer {dev_token}"},
    )
    assert resp.status_code == 409


def test_list_runs(client, dev_token):
    sid = _upload(client, dev_token)
    client.post(
        "/api/runs/execute",
        json={"script_id": sid, "params": {}},
        headers={"Authorization": f"Bearer {dev_token}"},
    )
    resp = client.get("/api/runs", headers={"Authorization": f"Bearer {dev_token}"})
    assert resp.status_code == 200
    assert len(resp.json()) >= 1


def test_operator_sees_own_runs(client, op_token, dev_token):
    sid = _upload(client, dev_token)
    client.post(
        "/api/runs/execute",
        json={"script_id": sid, "params": {}},
        headers={"Authorization": f"Bearer {dev_token}"},
    )
    resp = client.get("/api/runs", headers={"Authorization": f"Bearer {op_token}"})
    assert resp.status_code == 200
    assert len(resp.json()) == 0


def test_cancel_run(client, dev_token):
    sid = _upload(client, dev_token)
    run_resp = client.post(
        "/api/runs/execute",
        json={"script_id": sid, "params": {}},
        headers={"Authorization": f"Bearer {dev_token}"},
    )
    rid = run_resp.json()["id"]
    resp = client.post(f"/api/runs/{rid}/cancel", headers={"Authorization": f"Bearer {dev_token}"})
    assert resp.status_code == 200


def test_update_run_status(client, dev_token):
    sid = _upload(client, dev_token)
    run_resp = client.post(
        "/api/runs/execute",
        json={"script_id": sid, "params": {}},
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
