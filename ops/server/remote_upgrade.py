#!/usr/bin/env python3
"""从维护电脑安全升级远程 AutoScript Hub 服务端。"""

from __future__ import annotations

import argparse
import hashlib
import io
import os
from pathlib import Path, PurePosixPath
import re
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile
import uuid


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG = SCRIPT_DIR / "remote-upgrade.env"
SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")
SAFE_HOST_RE = re.compile(r"^[A-Za-z0-9_.:-]+$")
SAFE_USER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]*$")
SAFE_REPOSITORY_RE = re.compile(r"^[A-Za-z0-9._/-]+$")


REMOTE_SCRIPT = r'''set -eu
archive=$1
archive_sha256=$2
deploy_dir=$3
compose_file=$4
env_file=$5
data_dir=$6
port=$7
project_name=$8
image_repository=$9
version=${10}
skip_pull=${11}
work_dir=$(mktemp -d /tmp/autoscript-hub-upgrade.XXXXXX)
cleanup() {
  rm -rf "$work_dir" "$archive"
}
trap cleanup EXIT HUP INT TERM

actual_sha256=$(sha256sum "$archive" | awk '{print $1}')
if [ "$actual_sha256" != "$archive_sha256" ]; then
  echo "运维脚本包 SHA-256 校验失败" >&2
  exit 10
fi

tar -xzf "$archive" -C "$work_dir"
test -r "$compose_file"
test -r "$env_file"
test -d "$data_dir"
docker info >/dev/null
curl --fail --silent --show-error "http://127.0.0.1:$port/api/health/ready" >/dev/null

stamp=$(date -u +%Y%m%dT%H%M%SZ)
mkdir -p "$deploy_dir/history"
env_backup="$deploy_dir/history/.env.before-$version-$stamp"
cp -p "$env_file" "$env_backup"

target_image="$image_repository:$version"
tmp_env="$env_file.tmp.$$"
awk -v target="$target_image" '
  BEGIN { found = 0 }
  /^AUTOSCRIPT_SERVER_IMAGE=/ {
    print "AUTOSCRIPT_SERVER_IMAGE=" target
    found = 1
    next
  }
  { print }
  END {
    if (!found) print "AUTOSCRIPT_SERVER_IMAGE=" target
  }
' "$env_file" > "$tmp_env"
chmod "$(stat -c %a "$env_file")" "$tmp_env"
mv "$tmp_env" "$env_file"

set +e
AUTOSCRIPT_COMPOSE_FILE="$compose_file" \
AUTOSCRIPT_ENV_FILE="$env_file" \
AUTOSCRIPT_DATA_DIR="$data_dir" \
AUTOSCRIPT_PORT="$port" \
AUTOSCRIPT_PROJECT_NAME="$project_name" \
AUTOSCRIPT_IMAGE_REPOSITORY="$image_repository" \
AUTOSCRIPT_SKIP_PULL="$skip_pull" \
  sh "$work_dir/ops/server/upgrade.sh" "$version"
upgrade_status=$?
set -e
if [ "$upgrade_status" -ne 0 ]; then
  cp -p "$env_backup" "$env_file"
  echo "升级失败，部署配置已恢复；请检查上方回滚结果" >&2
  exit "$upgrade_status"
fi

ready=$(curl --fail --silent --show-error "http://127.0.0.1:$port/api/health/ready")
printf '%s' "$ready" | grep -F '"status":"ready"' >/dev/null
printf '%s' "$ready" | grep -F "\"version\":\"$version\"" >/dev/null
printf '%s' "$ready" | grep -F '"database":"ok"' >/dev/null
printf '%s' "$ready" | grep -F '"data_dir":"ok"' >/dev/null
printf '%s' "$ready" | grep -F '"migration":"ok"' >/dev/null
printf '远程升级完成：version=%s，配置备份=%s\n' "$version" "$env_backup"
'''


def parse_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for number, raw_line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            raise ValueError(f"{path}:{number} 不是 KEY=VALUE 格式")
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*", key):
            raise ValueError(f"{path}:{number} 配置键无效：{key}")
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        values[key] = value
    return values


def require(values: dict[str, str], key: str) -> str:
    value = values.get(key, "").strip()
    if not value:
        raise ValueError(f"缺少配置：{key}")
    if any(char in value for char in "\r\n\0"):
        raise ValueError(f"配置包含非法字符：{key}")
    return value


def remote_path(values: dict[str, str], key: str, default: str | None = None) -> str:
    value = values.get(key, default or "").strip()
    if not value:
        raise ValueError(f"缺少配置：{key}")
    path = PurePosixPath(value)
    if not path.is_absolute() or ".." in path.parts:
        raise ValueError(f"{key} 必须是无 .. 的远程绝对路径")
    return str(path)


def expand_local_path(value: str) -> Path:
    expanded = os.path.expandvars(os.path.expanduser(value))
    return Path(expanded).resolve()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_archive(output: Path) -> None:
    with tarfile.open(output, "w:gz") as archive:
        for source in sorted(SCRIPT_DIR.iterdir()):
            if source.is_file() and source.name not in {
                "remote-upgrade.env",
                "remote-upgrade.env.example",
                "remote_upgrade.py",
            } and source.suffix in {".sh", ".py"}:
                archive_name = f"ops/server/{source.name}"
                content = source.read_bytes().replace(b"\r\n", b"\n")
                info = tarfile.TarInfo(archive_name)
                info.size = len(content)
                info.mode = 0o755 if source.suffix == ".sh" else 0o644
                archive.addfile(info, io.BytesIO(content))


def command_path(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise RuntimeError(f"未找到命令：{name}")
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG, help="本机部署配置文件")
    parser.add_argument("--version", help="覆盖配置文件中的 TARGET_VERSION")
    args = parser.parse_args()

    config_path = args.config.expanduser().resolve()
    if not config_path.is_file():
        raise FileNotFoundError(
            f"未找到 {config_path}；请复制 remote-upgrade.env.example 后填写本机配置"
        )
    values = parse_env(config_path)
    host = require(values, "SSH_HOST")
    user = require(values, "SSH_USER")
    if not SAFE_HOST_RE.fullmatch(host) or host.startswith("-"):
        raise ValueError("SSH_HOST 格式无效")
    if not SAFE_USER_RE.fullmatch(user):
        raise ValueError("SSH_USER 格式无效")

    identity = expand_local_path(require(values, "SSH_IDENTITY_FILE"))
    if not identity.is_file():
        raise FileNotFoundError(f"SSH 私钥不存在：{identity}")

    deploy_dir = remote_path(values, "REMOTE_DEPLOY_DIR")
    compose_file = remote_path(values, "REMOTE_COMPOSE_FILE", f"{deploy_dir}/compose.yaml")
    env_file = remote_path(values, "REMOTE_ENV_FILE", f"{deploy_dir}/.env")
    data_dir = remote_path(values, "REMOTE_DATA_DIR")
    project_name = values.get("REMOTE_PROJECT_NAME", "").strip()
    if project_name and not re.fullmatch(r"[A-Za-z0-9_.-]+", project_name):
        raise ValueError("REMOTE_PROJECT_NAME 格式无效")
    port = require(values, "REMOTE_PORT")
    if not port.isdigit() or not 1 <= int(port) <= 65535:
        raise ValueError("REMOTE_PORT 必须在 1 到 65535 之间")
    version = (args.version or require(values, "TARGET_VERSION")).strip().lstrip("v")
    if not SEMVER_RE.fullmatch(version):
        raise ValueError(f"TARGET_VERSION 不是有效 SemVer：{version}")
    image_repository = require(values, "IMAGE_REPOSITORY").rstrip(":")
    if not SAFE_REPOSITORY_RE.fullmatch(image_repository) or "/" not in image_repository:
        raise ValueError("IMAGE_REPOSITORY 格式无效")
    skip_pull = values.get("SKIP_PULL", "0").strip()
    if skip_pull not in {"0", "1"}:
        raise ValueError("SKIP_PULL 只能是 0 或 1")

    ssh = command_path("ssh")
    scp = command_path("scp")
    destination = f"{user}@{host}"
    connection = [
        "-i", str(identity),
        "-o", "IdentitiesOnly=yes",
        "-o", "BatchMode=yes",
        "-o", "ConnectTimeout=10",
    ]

    with tempfile.TemporaryDirectory(prefix="autoscript-remote-upgrade-") as temp:
        archive = Path(temp) / "ops-server.tar.gz"
        build_archive(archive)
        archive_digest = sha256(archive)
        remote_archive = f"/tmp/autoscript-hub-upgrade-{uuid.uuid4().hex}.tar.gz"
        subprocess.run(
            [scp, *connection, str(archive), f"{destination}:{remote_archive}"],
            check=True,
        )
        remote_args = [
            remote_archive,
            archive_digest,
            deploy_dir,
            compose_file,
            env_file,
            data_dir,
            port,
            project_name,
            image_repository,
            version,
            skip_pull,
        ]
        remote_command = "sh -s -- " + " ".join(shlex.quote(value) for value in remote_args)
        subprocess.run(
            [ssh, *connection, destination, remote_command],
            # Windows 文本管道会把 LF 改写为 CRLF，远程 /bin/sh 会把 \r 识别为参数内容。
            input=REMOTE_SCRIPT.encode("utf-8"),
            check=True,
        )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"远程升级失败：{exc}", file=sys.stderr)
        raise SystemExit(1)
