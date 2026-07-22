from app.models import Run, Script, User
from app.routers import runs as runs_router


def _create_run(TestSession):
    db = TestSession()
    user = db.query(User).filter(User.username == "operator1").one()
    script = Script(name="log-script", type="py", latest_version=1, status="active")
    db.add(script)
    db.flush()
    run = Run(
        script_id=script.id,
        script_version=1,
        user_id=user.id,
        status="running",
    )
    db.add(run)
    db.commit()
    run_id = run.id
    db.close()
    return run_id


def test_default_log_file_uses_server_log_directory(tmp_path, monkeypatch):
    monkeypatch.setattr(runs_router, "LOGS_DIR", str(tmp_path))
    assert runs_router._default_log_file(12) == str(tmp_path / "12.log")


def test_log_chunks_append_by_utf8_byte_offset_and_are_idempotent(
    client, op_token, fresh_db, tmp_path, monkeypatch
):
    TestSession, _ = fresh_db
    run_id = _create_run(TestSession)
    monkeypatch.setattr(runs_router, "LOGS_DIR", str(tmp_path))
    headers = {"Authorization": f"Bearer {op_token}"}

    first = client.post(
        f"/api/runs/{run_id}/log/chunk",
        json={"offset": 0, "content": "开始\n"},
        headers=headers,
    )
    assert first.status_code == 200
    assert first.json() == {"offset": len("开始\n".encode("utf-8"))}

    duplicate = client.post(
        f"/api/runs/{run_id}/log/chunk",
        json={"offset": 0, "content": "开始\n"},
        headers=headers,
    )
    assert duplicate.status_code == 200
    assert duplicate.json() == first.json()

    second = client.post(
        f"/api/runs/{run_id}/log/chunk",
        json={"offset": first.json()["offset"], "content": "done\n"},
        headers=headers,
    )
    assert second.status_code == 200

    log = client.get(f"/api/runs/{run_id}/log", headers=headers)
    assert log.status_code == 200
    assert log.json()["log"] == "开始\ndone\n"


def test_log_chunk_rejects_gap_and_returns_server_offset(
    client, op_token, fresh_db, tmp_path, monkeypatch
):
    TestSession, _ = fresh_db
    run_id = _create_run(TestSession)
    monkeypatch.setattr(runs_router, "LOGS_DIR", str(tmp_path))

    response = client.post(
        f"/api/runs/{run_id}/log/chunk",
        json={"offset": 12, "content": "late"},
        headers={"Authorization": f"Bearer {op_token}"},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["offset"] == 0
