from pathlib import Path
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import os
import shutil
import subprocess
import sys
import threading
import zipfile

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from shared.update_manifest import UpdateManifest


ROOT = Path(__file__).resolve().parents[2]


def test_standalone_skill_contract_snapshot_matches_live_contract():
    live = (ROOT / "shared" / "script_contract.py").read_text(encoding="utf-8")
    snapshot = (
        ROOT
        / "skills"
        / "autoscript-script-authoring"
        / "scripts"
        / "contract_snapshot.py"
    ).read_text(encoding="utf-8")

    assert snapshot.rstrip() == live.rstrip() + "\n\nvalidate = validate_script"


def test_standalone_skill_validator_enforces_detailed_contract_rules(tmp_path):
    source_skill = ROOT / "skills" / "autoscript-script-authoring"
    standalone_skill = tmp_path / "autoscript-script-authoring"
    shutil.copytree(source_skill, standalone_skill)
    invalid_script = tmp_path / "invalid_select.py"
    invalid_script.write_text(
        """def config():
    return {
        'name': 'invalid', 'version': '1.0.0', 'description': '', 'category': '',
        'params': [{'key': 'mode', 'type': 'select', 'label': 'Mode',
                    'options': ['safe'], 'default': 'fast'}],
        'requirements': [], 'timeout': 30, 'presets': []}

def main(mode):
    return None
""",
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            sys.executable,
            str(standalone_skill / "scripts" / "validate_script.py"),
            str(invalid_script),
            "--strict",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 1
    assert "params.select-default" in completed.stdout


def test_standalone_skill_validator_reports_rule_codes_with_legacy_console_encoding(tmp_path):
    source_skill = ROOT / "skills" / "autoscript-script-authoring"
    standalone_skill = tmp_path / "autoscript-script-authoring"
    shutil.copytree(source_skill, standalone_skill)
    invalid_script = tmp_path / "invalid_select.py"
    invalid_script.write_text(
        """def config():
    return {'name': 'invalid', 'version': '1.0.0', 'description': '', 'category': '',
            'params': [{'key': 'mode', 'type': 'select', 'label': 'Mode',
                        'options': ['safe'], 'default': 'fast'}],
            'requirements': [], 'timeout': 30, 'presets': []}

def main(mode):
    return None
""",
        encoding="utf-8",
    )
    environment = os.environ | {"PYTHONIOENCODING": "cp1252"}

    completed = subprocess.run(
        [
            sys.executable,
            str(standalone_skill / "scripts" / "validate_script.py"),
            str(invalid_script),
            "--strict",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env=environment,
    )

    assert completed.returncode == 1
    assert "params.select-default" in completed.stdout
    assert "UnicodeEncodeError" not in completed.stderr


def test_asset_builder_outputs_standalone_skill_and_deploy_bundles(tmp_path):
    completed = subprocess.run(
        [sys.executable, "release/scripts/build_release_assets.py", "--version", "0.9.0", "--output", str(tmp_path)],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr

    skill = tmp_path / "autoscript-script-authoring-0.9.0.zip"
    deploy = tmp_path / "autoscript-hub-server-deploy-0.9.0.zip"
    with zipfile.ZipFile(skill) as bundle:
        assert "autoscript-script-authoring/SKILL.md" in bundle.namelist()
        assert "autoscript-script-authoring/agents/openai.yaml" in bundle.namelist()
    with zipfile.ZipFile(deploy) as bundle:
        assert "autoscript-hub-server/deploy/compose.yaml" in bundle.namelist()
        assert "autoscript-hub-server/ops/server/backup.sh" in bundle.namelist()
    assert "autoscript-script-authoring-0.9.0.zip" in (tmp_path / "SHA256SUMS.txt").read_text("utf-8")


def test_skill_templates_validate_strictly_and_return_supported_result_types(tmp_path):
    skill = ROOT / "skills" / "autoscript-script-authoring"
    validator = skill / "scripts" / "validate_script.py"
    single = skill / "assets" / "single_script_template.py"
    multi = skill / "assets" / "multi_script"
    multi_zip = tmp_path / "multi.zip"

    for candidate in (single, multi / "main.py"):
        completed = subprocess.run(
            [sys.executable, str(validator), str(candidate), "--strict"],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        assert completed.returncode == 0, completed.stdout + completed.stderr

    packaged = subprocess.run(
        [
            sys.executable,
            str(skill / "scripts" / "package_script.py"),
            str(multi),
            str(multi_zip),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert packaged.returncode == 0, packaged.stdout + packaged.stderr

    executed = subprocess.run(
        [sys.executable, "-c", "import main; print(repr(main.main('value')))"],
        cwd=multi,
        capture_output=True,
        text=True,
    )
    assert executed.returncode == 0, executed.stdout + executed.stderr
    assert executed.stdout.strip() == "None"


def test_manifest_generator_signs_installer_for_runtime_parser(tmp_path):
    installer = tmp_path / "AutoScript-Hub-Setup-0.9.1.exe"
    installer.write_bytes(b"installer")
    key = Ed25519PrivateKey.generate()
    private = tmp_path / "key.pem"
    private.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))

    completed = subprocess.run(
        [
            sys.executable,
            "release/scripts/make_update_manifest.py",
            "--version", "0.9.1",
            "--installer", str(installer),
            "--private-key", str(private),
            "--url", "https://gitee.example/installer.exe",
            "--url", "https://github.example/installer.exe",
            "--output", str(tmp_path),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    raw = (tmp_path / "autoscript-hub-update.json").read_bytes()
    signature = (tmp_path / "autoscript-hub-update.json.sig").read_bytes()
    public = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)

    assert UpdateManifest.from_bytes(raw, signature, public).version == "0.9.1"


def test_workflows_cover_windows_dual_arch_images_and_both_release_hosts():
    ci = (ROOT / ".github/workflows/ci.yml").read_text("utf-8")
    release = (ROOT / ".github/workflows/release.yml").read_text("utf-8")

    assert "windows-latest" in ci
    assert "ubuntu-latest" in ci
    assert "npm run build" in ci
    assert "linux/amd64,linux/arm64" in release
    assert "release/windows/build.ps1" in release
    assert "GITEE_TOKEN" in release
    assert "ghcr.io" in release
    assert "autoscript-script-authoring" in release
    assert "docker/metadata-action@v5" in release
    assert "type=semver,pattern={{version}}" in release
    assert "type=raw,value=beta" in release
    assert "type=raw,value=stable" in release
    assert "type=raw,value=latest" in release
    assert '"linux/amd64:18090" "linux/arm64:18091"' in release
    assert 'docker run --platform "$platform"' in release
    assert '"${{ github.ref_name }}".TrimStart' not in release
    assert "write_checksums.py" in release
    assert 'pattern: "!*.dockerbuild"' in release


def test_release_windows_job_uses_the_exact_private_runtime_version():
    release = (ROOT / ".github/workflows/release.yml").read_text("utf-8")

    assert "python-version: '3.11.9'" in release


def test_checksum_writer_covers_all_final_release_assets(tmp_path):
    for name, content in {
        "AutoScript-Hub-Setup-0.9.0.exe": b"installer",
        "autoscript-script-authoring-0.9.0.zip": b"skill",
        "autoscript-hub-server-deploy-0.9.0.zip": b"deploy",
        "autoscript-hub-update.json": b"manifest",
        "autoscript-hub-update.json.sig": b"signature",
    }.items():
        (tmp_path / name).write_bytes(content)
    (tmp_path / "autoscript-hub-validation-source.tar.gz").write_bytes(b"temporary source")
    (tmp_path / "build-notes.txt").write_text("temporary", encoding="utf-8")

    completed = subprocess.run(
        [sys.executable, "release/scripts/write_checksums.py", "--directory", str(tmp_path)],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    checksum = (tmp_path / "SHA256SUMS.txt").read_text("utf-8")
    for name in (
        "AutoScript-Hub-Setup-0.9.0.exe",
        "autoscript-script-authoring-0.9.0.zip",
        "autoscript-hub-server-deploy-0.9.0.zip",
        "autoscript-hub-update.json",
        "autoscript-hub-update.json.sig",
    ):
        assert name in checksum
    assert "SHA256SUMS.txt" not in checksum
    assert "autoscript-hub-validation-source.tar.gz" not in checksum
    assert "build-notes.txt" not in checksum


def test_anonymous_mirror_verifier_requires_identical_assets(tmp_path):
    release = tmp_path / "release"
    release.mkdir()
    for name, content in {
        "AutoScript-Hub-Setup-0.9.0.exe": b"installer",
        "autoscript-script-authoring-0.9.0.zip": b"skill",
        "autoscript-hub-server-deploy-0.9.0.zip": b"deploy",
        "autoscript-hub-update.json": b"manifest",
        "autoscript-hub-update.json.sig": b"signature",
    }.items():
        (release / name).write_bytes(content)
    subprocess.run(
        [sys.executable, "release/scripts/write_checksums.py", "--directory", str(release)],
        cwd=ROOT,
        check=True,
    )
    webroot = tmp_path / "web"
    shutil.copytree(release, webroot / "github")
    shutil.copytree(release, webroot / "gitee")

    class QuietHandler(SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(
        ("127.0.0.1", 0),
        partial(QuietHandler, directory=str(webroot)),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        command = [
            sys.executable,
            "release/scripts/verify_release_mirrors.py",
            "--directory", str(release),
            "--base-url", f"{base}/github",
            "--base-url", f"{base}/gitee",
            "--attempts", "1",
            "--delay", "0",
        ]
        completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
        assert completed.returncode == 0, completed.stdout + completed.stderr

        (webroot / "gitee" / "autoscript-hub-update.json").write_bytes(b"divergent")
        rejected = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
        assert rejected.returncode != 0
        assert "mismatch" in (rejected.stdout + rejected.stderr).lower()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
