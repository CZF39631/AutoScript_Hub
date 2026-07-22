from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _read(path):
    return (ROOT / path).read_text(encoding="utf-8")


def test_pyinstaller_builds_three_executables_in_one_collection():
    spec = _read("release/windows/autoscript_hub.spec")

    assert "MERGE(" in spec
    assert 'name="AutoScriptHub"' in spec
    assert 'name="AutoScriptAgent"' in spec
    assert 'name="AutoScriptUpdater"' in spec
    assert "COLLECT(" in spec
    assert "client/update/update-public-key.b64" in spec.replace("\\", "/")
    assert "autoscript-build" in spec


def test_updater_is_self_contained_before_it_is_copied_outside_install_tree():
    spec = _read("release/windows/autoscript_hub.spec")
    updater = _read("client/agent/updater.py")

    assert "updater.binaries" in spec
    assert "updater.datas" in spec
    assert "exclude_binaries=False" in spec
    assert "updater-bootstrap-" in updater
    assert "shutil.copy2" in updater


def test_build_injects_version_and_channel_into_all_frozen_entrypoints():
    build = _read("release/windows/build.ps1")
    entries = "\n".join(
        _read(path)
        for path in (
            "release/windows/entry_ui.py",
            "release/windows/entry_agent.py",
            "release/windows/entry_updater.py",
        )
    )

    assert "autoscript_build_info.py" in build
    assert "AUTOSCRIPT_VERSION" in entries
    assert "AUTOSCRIPT_CHANNEL" in entries
    assert entries.count("from autoscript_build_info import CHANNEL, VERSION") == 3


def test_runtime_staging_requires_exact_python_3119_and_proves_venv_support():
    stage = _read("release/windows/stage_python_runtime.ps1")
    fetch = _read("release/windows/fetch_python_runtime.ps1")

    assert "3.11.9" in stage
    assert "sys.base_prefix" in stage
    assert "Lib\\site-packages" in stage
    assert '"-m", "venv"' in stage
    assert '"-m", "pip", "--version"' in stage
    assert "python-3.11.9-amd64.exe" not in fetch
    assert "MicrosoftEdgeWebview2Setup.exe" in fetch


def test_inno_installs_per_user_private_runtime_and_preserves_data():
    installer = _read("release/windows/installer.iss")

    assert "PrivilegesRequired=lowest" in installer
    assert "{localappdata}\\Programs\\AutoScript Hub" in installer
    assert "windows-runtime\\python\\*" in installer
    assert "python-3.11.9-amd64.exe" not in installer
    assert "Exec(PrivatePython" in installer
    assert "ResultCode <> 0" in installer
    assert "IsWebView2RuntimeInstalled" in installer
    assert "if not IsWebView2RuntimeInstalled then" in installer
    assert "Exec(WebViewInstaller" in installer
    assert "{localappdata}\\AutoScriptHub" in installer
    assert "AutoScriptHub.exe" in installer
    assert "AutoScriptAgent.exe" in installer
    assert "AutoScriptUpdater.exe" in installer


def test_build_enforces_tests_and_95mb_gitee_gate():
    build = _read("release/windows/build.ps1")

    assert "[string]$PythonExe" in build
    assert "& $PythonExe -m pip install" in build
    assert "backend/requirements.txt" in build
    assert "client/requirements.txt" in build
    assert "npm test" in build
    assert "pytest" in build
    assert "stage_python_runtime.ps1" in build
    assert "windows-runtime" in build
    assert "95MB" in build
    assert "ISCC" in build
    assert "LOCALAPPDATA" in build


def test_ui_entry_starts_independent_agent_and_writes_startup_marker():
    entry = _read("release/windows/entry_ui.py")

    assert "AutoScriptAgent.exe" in entry
    assert "write_startup_marker" in entry
    assert ".terminate(" not in entry
    assert "is_setup_complete" in entry
    assert "subprocess.Popen([sys.executable]" in entry


def test_pytest_does_not_collect_generated_release_runtime():
    pytest_config = _read("pytest.ini")

    assert "norecursedirs" in pytest_config
    assert "release-output" in pytest_config


def test_environment_ui_uses_managed_runtime_instead_of_arbitrary_venv_paths():
    page = _read("frontend/src/pages/Environments.jsx")

    assert "/local/runtime" in page
    assert "私有 Python 3.11.9" in page
    assert "/create-venv" not in page
    assert "/delete-venv" not in page
    assert "/detect-python-versions" not in page


def test_settings_ui_exposes_public_and_lan_update_sources():
    page = _read("frontend/src/pages/Settings.jsx")

    assert "github_update_repository" in page
    assert "update_manifest_urls" in page
    assert "Gitee" in page
    assert "局域网" in page
