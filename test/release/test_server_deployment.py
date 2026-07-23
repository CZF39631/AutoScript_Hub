from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _read(relative_path):
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_dockerfile_is_multi_stage_non_root_and_ready_checked():
    dockerfile = _read("Dockerfile")

    assert "ARG BASE_REGISTRY=docker.io/library" in dockerfile
    assert "FROM ${BASE_REGISTRY}/node:20" in dockerfile
    assert "FROM ${BASE_REGISTRY}/python:3.11-slim" in dockerfile
    assert "USER autoscript" in dockerfile
    assert "HEALTHCHECK" in dockerfile
    assert "/api/health/ready" in dockerfile
    assert "frontend/dist" in dockerfile
    assert "/app/autoscript-build.json" in dockerfile
    assert dockerfile.index("pip install") < dockerfile.index("/app/autoscript-build.json")


def test_local_compose_can_select_a_registry_mirror_without_daemon_changes():
    compose = _read("deploy/compose.local.yaml")
    example_env = _read("deploy/.env.example")

    assert "BASE_REGISTRY: ${AUTOSCRIPT_BASE_REGISTRY:-docker.io/library}" in compose
    assert "AUTOSCRIPT_BASE_REGISTRY=docker.io/library" in example_env


def test_compose_is_lan_first_single_instance_with_persistent_data():
    compose = _read("deploy/compose.yaml")
    example_env = _read("deploy/.env.example")

    assert compose.count("  server:\n") == 1
    assert "${AUTOSCRIPT_SERVER_IMAGE:-ghcr.io/czf39631/autoscript-hub-server:0.9.1}" in compose
    assert "AUTOSCRIPT_SERVER_IMAGE=ghcr.io/czf39631/autoscript-hub-server:0.9.1" in example_env
    assert "AUTOSCRIPT_IMAGE_TAG=0.9\n" not in example_env
    assert "${AUTOSCRIPT_BIND_ADDRESS:-0.0.0.0}" in compose
    assert "${AUTOSCRIPT_DATA_DIR:-/opt/autoscript-hub/data}:/data" in compose
    assert "restart: unless-stopped" in compose
    assert "replicas:" not in compose


def test_container_migrates_before_starting_uvicorn():
    entrypoint = _read("deploy/docker-entrypoint.sh")

    migration = entrypoint.index("upgrade_database")
    server = entrypoint.index("uvicorn")
    assert migration < server
    assert "exec" in entrypoint


def test_operational_scripts_have_strict_mode_and_recovery_contracts():
    backup = _read("ops/server/backup.sh")
    restore = _read("ops/server/restore.sh")
    upgrade = _read("ops/server/upgrade.sh")
    rollback = _read("ops/server/rollback.sh")
    common = _read("ops/server/common.sh")

    for script in (backup, restore, upgrade, rollback):
        assert "set -eu" in script
    assert "backup_sqlite.py" in backup
    assert "verify" in restore
    assert "wait_ready" in upgrade
    assert "health/ready" in common
    assert "AUTOSCRIPT_PROJECT_NAME" in common
    assert "--project-name" in common
    assert "rollback.sh" in upgrade
    assert "restore.sh" in rollback
    assert "compose exec -T server python /app/ops/backup_sqlite.py" in backup
    assert "compose run --rm --no-deps --entrypoint python server" in restore
    assert "python3 " not in backup
    assert "python3 " not in restore


def test_upgrade_and_rollback_can_use_preloaded_images_on_offline_lan_hosts():
    common = _read("ops/server/common.sh")
    upgrade = _read("ops/server/upgrade.sh")
    rollback = _read("ops/server/rollback.sh")

    assert "pull_server()" in common
    assert "AUTOSCRIPT_SKIP_PULL" in common
    assert "pull_server" in upgrade
    assert "pull_server" in rollback
    assert "compose pull server" not in upgrade
    assert "compose pull server" not in rollback


def test_failed_upgrade_rolls_back_with_the_previous_immutable_image_before_restore():
    common = _read("ops/server/common.sh")
    upgrade = _read("ops/server/upgrade.sh")
    rollback = _read("ops/server/rollback.sh")

    assert "current_server_image_id" in common
    assert "sha256:" in common
    assert "OLD_IMAGE=$(current_server_image_id)" in upgrade
    assert 'rollback.sh" "$OLD_IMAGE" "$BACKUP_DIR"' in upgrade
    assert "AUTOSCRIPT_SERVER_IMAGE" in rollback
    assert rollback.index("export AUTOSCRIPT_SERVER_IMAGE") < rollback.index("restore.sh")
    assert rollback.index("pull_server") < rollback.index("compose stop server")


def test_upgrade_requires_three_consecutive_ready_probes():
    common = _read("ops/server/common.sh")

    assert "required_successes=${2:-3}" in common
    assert "consecutive=$((consecutive + 1))" in common
    assert "consecutive=0" in common
    assert 'if [ "$consecutive" -ge "$required_successes" ]' in common


def test_operational_scripts_do_not_require_preserved_executable_bits():
    upgrade = _read("ops/server/upgrade.sh")
    rollback = _read("ops/server/rollback.sh")

    assert 'sh "$SCRIPT_DIR/backup.sh"' in upgrade
    assert 'sh "$SCRIPT_DIR/rollback.sh"' in upgrade
    assert 'sh "$SCRIPT_DIR/restore.sh"' in rollback


def test_release_image_does_not_copy_development_secrets():
    dockerignore = _read(".dockerignore")
    dockerfile = _read("Dockerfile")

    assert "config.json" in dockerignore
    assert "client_config.json" in dockerignore
    assert "COPY . ." not in dockerfile
    assert "ops/server/backup_sqlite.py" in dockerfile


def test_runtime_requirements_exclude_pytest_but_build_paths_install_it():
    requirements = _read("backend/requirements.txt")
    ci = _read(".github/workflows/ci.yml")
    windows_build = _read("release/windows/build.ps1")

    assert "pytest" not in requirements.lower()
    assert "pytest==7.4.3" in ci
    assert "pytest==7.4.3" in windows_build
