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
    assert data["script_semantic_version"] == "1.0.0"


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
    assert resp.json()[0]["script_semantic_version"] == "1.0.0"


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
    agent_id = client.post(
        "/api/agents/register",
        json={"machine_name": "status-owner", "agent_version": "1.0.0"},
        headers={"Authorization": f"Bearer {dev_token}"},
    ).json()["id"]
    sid = _upload(client, dev_token)
    run_resp = client.post(
        "/api/runs/execute",
        json={"script_id": sid, "params": {"url_file": "C:/test.txt"}},
        headers={"Authorization": f"Bearer {dev_token}"},
    )
    rid = run_resp.json()["id"]
    claimed = client.post(
        f"/api/runs/{rid}/claim",
        json={"agent_id": agent_id},
        headers={"Authorization": f"Bearer {dev_token}"},
    )
    assert claimed.status_code == 200
    resp = client.patch(
        f"/api/runs/{rid}/status",
        json={"status": "success", "agent_id": agent_id, "log_path": "storage/logs/1.log"},
        headers={"Authorization": f"Bearer {dev_token}"},
    )
    assert resp.status_code == 200
    detail = client.get(f"/api/runs/{rid}", headers={"Authorization": f"Bearer {dev_token}"})
    assert detail.json()["status"] == "success"
    assert detail.json()["script_semantic_version"] == "1.0.0"
    assert detail.json()["duration_sec"] is not None
    assert detail.json()["log_path"] is None


def test_pending_run_cannot_be_marked_running_without_an_atomic_claim(client, dev_token):
    agent_id = client.post(
        "/api/agents/register",
        json={"machine_name": "legacy-agent", "agent_version": "0.9.0"},
        headers={"Authorization": f"Bearer {dev_token}"},
    ).json()["id"]
    sid = _upload(client, dev_token)
    run_id = client.post(
        "/api/runs/execute",
        json={"script_id": sid, "params": {"url_file": "C:/test.txt"}},
        headers={"Authorization": f"Bearer {dev_token}"},
    ).json()["id"]

    response = client.patch(
        f"/api/runs/{run_id}/status",
        json={"status": "running", "agent_id": agent_id},
        headers={"Authorization": f"Bearer {dev_token}"},
    )

    assert response.status_code == 409


def test_result_files_are_client_local_and_server_has_no_open_or_download_routes():
    from app.main import app

    paths = {route.path for route in app.routes}
    assert "/api/runs/{run_id}/open-result" not in paths
    assert "/api/runs/{run_id}/download" not in paths


def test_agent_claims_run_through_atomic_claim_endpoint(client, dev_token):
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

    updated = client.post(
        f"/api/runs/{run_id}/claim",
        json={"agent_id": agent_id},
        headers={"Authorization": f"Bearer {dev_token}"},
    )
    detail = client.get(
        f"/api/runs/{run_id}",
        headers={"Authorization": f"Bearer {dev_token}"},
    )

    assert updated.status_code == 200
    assert detail.json()["agent_id"] == agent_id


def test_claiming_pending_run_is_atomic_and_binds_the_first_agent(client, dev_token):
    first_agent = client.post(
        "/api/agents/register",
        json={"machine_name": "claim-first", "agent_version": "1.0.0"},
        headers={"Authorization": f"Bearer {dev_token}"},
    ).json()["id"]
    second_agent = client.post(
        "/api/agents/register",
        json={"machine_name": "claim-second", "agent_version": "1.0.0"},
        headers={"Authorization": f"Bearer {dev_token}"},
    ).json()["id"]
    sid = _upload(client, dev_token)
    run_id = client.post(
        "/api/runs/execute",
        json={"script_id": sid, "params": {"url_file": "C:/test.txt"}},
        headers={"Authorization": f"Bearer {dev_token}"},
    ).json()["id"]

    first = client.post(
        f"/api/runs/{run_id}/claim",
        json={"agent_id": first_agent},
        headers={"Authorization": f"Bearer {dev_token}"},
    )
    second = client.post(
        f"/api/runs/{run_id}/claim",
        json={"agent_id": second_agent},
        headers={"Authorization": f"Bearer {dev_token}"},
    )

    assert first.status_code == 200
    assert first.json()["status"] == "running"
    assert first.json()["agent_id"] == first_agent
    assert second.status_code == 409
    detail = client.get(f"/api/runs/{run_id}", headers={"Authorization": f"Bearer {dev_token}"})
    assert detail.json()["agent_id"] == first_agent


def test_claimed_run_rejects_status_update_from_another_agent(client, dev_token):
    owner_agent = client.post(
        "/api/agents/register",
        json={"machine_name": "claim-owner", "agent_version": "1.0.0"},
        headers={"Authorization": f"Bearer {dev_token}"},
    ).json()["id"]
    other_agent = client.post(
        "/api/agents/register",
        json={"machine_name": "claim-other", "agent_version": "1.0.0"},
        headers={"Authorization": f"Bearer {dev_token}"},
    ).json()["id"]
    sid = _upload(client, dev_token)
    run_id = client.post(
        "/api/runs/execute",
        json={"script_id": sid, "params": {"url_file": "C:/test.txt"}},
        headers={"Authorization": f"Bearer {dev_token}"},
    ).json()["id"]
    client.post(
        f"/api/runs/{run_id}/claim",
        json={"agent_id": owner_agent},
        headers={"Authorization": f"Bearer {dev_token}"},
    )

    response = client.patch(
        f"/api/runs/{run_id}/status",
        json={"status": "success", "agent_id": other_agent},
        headers={"Authorization": f"Bearer {dev_token}"},
    )

    assert response.status_code == 403
