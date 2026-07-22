from app import main as main_module


def test_liveness_reports_release_identity(client, monkeypatch):
    monkeypatch.setenv("AUTOSCRIPT_VERSION", "0.9.0")
    monkeypatch.setenv("AUTOSCRIPT_CHANNEL", "beta")

    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "version": "0.9.0",
        "channel": "beta",
    }


def test_readiness_reports_database_data_and_migration_checks(client, monkeypatch):
    monkeypatch.setattr(
        main_module,
        "_readiness_checks",
        lambda: {"database": "ok", "data_dir": "ok", "migration": "ok"},
    )

    response = client.get("/api/health/ready")

    assert response.status_code == 200
    assert response.json()["status"] == "ready"
    assert response.json()["checks"] == {
        "database": "ok",
        "data_dir": "ok",
        "migration": "ok",
    }


def test_readiness_returns_503_when_any_check_fails(client, monkeypatch):
    monkeypatch.setattr(
        main_module,
        "_readiness_checks",
        lambda: {
            "database": "ok",
            "data_dir": "error: not writable",
            "migration": "ok",
        },
    )

    response = client.get("/api/health/ready")

    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"
    assert response.json()["checks"]["data_dir"].startswith("error:")
