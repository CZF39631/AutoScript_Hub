#!/usr/bin/env python3
"""AutoScript Hub 应用支持工具：目标识别、工单诊断和安全脚本发布。"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys
from typing import Any
from urllib.parse import urlsplit, urlunsplit


SKILL_DIR = Path(__file__).resolve().parent.parent


def _find_repo_root() -> Path:
    for candidate in [Path.cwd().resolve(), *Path(__file__).resolve().parents]:
        if (candidate / "client").is_dir() and (candidate / "shared").is_dir():
            return candidate
    raise RuntimeError("请在 AutoScript Hub 仓库中运行此工具")


REPO_ROOT = _find_repo_root()
sys.path.insert(0, str(REPO_ROOT))

import requests  # noqa: E402
from packaging.version import InvalidVersion, Version  # noqa: E402
from client.runtime.paths import ClientPaths  # noqa: E402
from client.ui.config_manager import load_config  # noqa: E402
from shared.script_contract import validate_script  # noqa: E402


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")


PLAN_NAME = "support-publish-plan.json"
PLAN_TTL_MINUTES = 30


class SupportError(RuntimeError):
    pass


def _redact_url(match: re.Match) -> str:
    text = match.group(0)
    try:
        value = urlsplit(text)
    except ValueError:
        return "[URL已隐藏]"
    host = value.hostname or "host"
    port = f":{value.port}" if value.port else ""
    path = value.path if len(value.path) <= 80 else value.path[:77] + "..."
    return urlunsplit((value.scheme, host + port, path, "[参数已隐藏]" if value.query else "", ""))


def redact(value: Any) -> Any:
    """递归隐藏日志和接口文本中的常见凭据。"""
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            if any(word in str(key).lower() for word in ("password", "token", "secret", "authorization", "cookie")):
                result[key] = "[已隐藏]"
            else:
                result[key] = redact(item)
        return result
    if isinstance(value, list):
        return [redact(item) for item in value]
    if not isinstance(value, str):
        return value
    text = re.sub(r"https?://[^\s\"'<>]+", _redact_url, value)
    text = re.sub(
        r"(?i)\b(password|token|secret|sign|trade_no|auth(?:_key|_token|_type)?)\s*[=:]\s*[^\s&,;]+",
        lambda match: f"{match.group(1)}=[已隐藏]",
        text,
    )
    text = re.sub(r"(?i)([A-Z]:\\Users\\)[^\\]+", r"\1[用户]", text)
    return text


def _json_print(value: Any) -> None:
    print(json.dumps(redact(value), ensure_ascii=False, indent=2, sort_keys=True))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _origin(url: str) -> str:
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise SupportError("当前客户端 server_url 无效")
    netloc = parsed.hostname
    if parsed.port:
        netloc += f":{parsed.port}"
    return urlunsplit((parsed.scheme, netloc, "", "", ""))


class SupportClient:
    def __init__(self):
        self.config = load_config()
        self.base_url = str(self.config.get("server_url") or "").rstrip("/")
        self.origin = _origin(self.base_url)
        self.username = str(self.config.get("username") or "").strip()
        self.password = str(self.config.get("password") or "")
        self.session = requests.Session()
        self.token = ""
        self.user = {}

    def authenticate(self) -> None:
        if not self.username or not self.password:
            raise SupportError("当前客户端没有可用的已保存登录凭据")
        try:
            response = self.session.post(
                self.base_url + "/api/auth/login",
                json={"username": self.username, "password": self.password},
                timeout=20,
            )
        except requests.RequestException as exc:
            raise SupportError(f"无法连接当前服务器：{self.origin}") from exc
        if response.status_code != 200:
            raise SupportError(f"当前服务器登录失败：HTTP {response.status_code}")
        payload = response.json()
        self.token = str(payload.get("token") or "")
        self.user = payload.get("user") or {}
        if not self.token:
            raise SupportError("登录响应缺少 token")

    @property
    def headers(self) -> dict:
        return {"Authorization": "Bearer " + self.token}

    def request(self, method: str, path: str, **kwargs):
        if not self.token:
            self.authenticate()
        try:
            response = self.session.request(
                method,
                self.base_url + path,
                headers={**self.headers, **kwargs.pop("headers", {})},
                timeout=kwargs.pop("timeout", 30),
                **kwargs,
            )
        except requests.RequestException as exc:
            raise SupportError(f"请求失败：{method} {path}") from exc
        if response.status_code >= 400:
            try:
                detail = response.json().get("detail") or response.json().get("error")
            except (ValueError, AttributeError):
                detail = None
            suffix = f"：{redact(str(detail))}" if detail else ""
            raise SupportError(f"{method} {path} 返回 HTTP {response.status_code}{suffix}")
        return response

    def marketplace(self) -> list[dict]:
        return self.request("GET", "/api/scripts/marketplace").json()

    def script_detail(self, script_id: int) -> dict:
        return self.request("GET", f"/api/scripts/{script_id}").json()


def command_target(_args) -> None:
    client = SupportClient()
    client.authenticate()
    print(
        f"目标：{client.origin}｜用户：{client.username}｜"
        f"角色：{client.user.get('role', '-')}｜来源：当前客户端配置"
    )


def command_issues(_args) -> None:
    client = SupportClient()
    issues = client.request("GET", "/api/issues", params={"status": "open"}).json()
    rows = [
        {
            "id": item.get("id"),
            "title": item.get("title"),
            "description": item.get("description"),
            "script_name": item.get("script_name"),
            "username": item.get("username"),
            "run_id": item.get("run_id"),
            "created_at": item.get("created_at"),
            "error_msg": item.get("error_msg"),
        }
        for item in issues
    ]
    _json_print({"target": client.origin, "count": len(rows), "issues": rows})


def _find_issue(client: SupportClient, issue_id: int) -> dict:
    issues = client.request("GET", "/api/issues").json()
    issue = next((item for item in issues if int(item.get("id", -1)) == issue_id), None)
    if issue is None:
        raise SupportError(f"未找到工单 #{issue_id}")
    return issue


def command_issue(args) -> None:
    client = SupportClient()
    issue = _find_issue(client, args.issue_id)
    run = None
    if issue.get("run_id"):
        run = client.request("GET", f"/api/runs/{issue['run_id']}").json()
        run = {
            key: run.get(key)
            for key in (
                "id", "script_id", "script_version", "script_semantic_version",
                "status", "error_msg", "started_at", "finished_at", "duration_sec",
            )
        }
    log_payload = client.request("GET", f"/api/issues/{args.issue_id}/log").json()
    log_lines = str(log_payload.get("log") or "").splitlines()[-args.log_lines:]
    _json_print({
        "target": client.origin,
        "issue": {
            key: issue.get(key)
            for key in (
                "id", "title", "description", "status", "script_id", "script_name",
                "username", "run_id", "created_at", "error_msg",
            )
        },
        "run": run,
        "log_tail": "\n".join(log_lines),
    })


def _select_script(client: SupportClient, script_id: int | None, name: str | None) -> dict:
    scripts = client.marketplace()
    if script_id is not None:
        matches = [item for item in scripts if int(item.get("id", -1)) == script_id]
    else:
        matches = [item for item in scripts if item.get("name") == name]
    if len(matches) != 1:
        raise SupportError(f"目标脚本匹配数量为 {len(matches)}，要求恰好为 1")
    return matches[0]


def command_marketplace(args) -> None:
    client = SupportClient()
    scripts = client.marketplace()
    if args.name:
        scripts = [item for item in scripts if item.get("name") == args.name]
    _json_print({
        "target": client.origin,
        "scripts": [
            {
                "id": item.get("id"),
                "name": item.get("name"),
                "platform_version": item.get("latest_version"),
                "semantic_version": item.get("latest_semantic_version"),
                "status": item.get("status"),
            }
            for item in scripts
        ],
    })


def command_download(args) -> None:
    client = SupportClient()
    detail = client.script_detail(args.script_id)
    response = client.request("GET", f"/api/scripts/{args.script_id}/download", timeout=60)
    output = Path(args.output).expanduser().resolve()
    if output.exists() and not args.overwrite:
        raise SupportError(f"输出文件已存在：{output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".tmp")
    temporary.write_bytes(response.content)
    os.replace(temporary, output)
    _json_print({
        "target": client.origin,
        "script_id": detail.get("id"),
        "semantic_version": detail.get("latest_semantic_version"),
        "output": str(output),
        "sha256": _sha256(output),
    })


def _validate_artifact(path: Path) -> dict:
    if not path.is_file() or path.suffix.lower() not in {".py", ".zip"}:
        raise SupportError("发布文件必须是存在的 .py 或 .zip")
    report = validate_script(path, strict=True)
    if not report.ok:
        messages = "；".join(issue.message for issue in report.errors)
        raise SupportError("脚本契约验证失败：" + messages)
    if not isinstance(report.config, dict):
        raise SupportError("脚本缺少静态 config")
    return report.config


def _plan_path() -> Path:
    paths = ClientPaths.from_environment()
    paths.ensure()
    return paths.config_dir / PLAN_NAME


def _write_plan(plan: dict) -> None:
    path = _plan_path()
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _read_plan() -> dict:
    path = _plan_path()
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SupportError("没有可执行的发布计划，请先运行 publish-plan") from exc
    if not isinstance(value, dict):
        raise SupportError("发布计划格式无效")
    return value


def command_publish_plan(args) -> None:
    client = SupportClient()
    client.authenticate()
    artifact = Path(args.artifact).expanduser().resolve()
    config = _validate_artifact(artifact)
    target = _select_script(client, args.script_id, args.name)
    detail = client.script_detail(int(target["id"]))
    current = str(detail.get("latest_semantic_version") or "")
    new_version = str(config.get("version") or "")
    if current != args.expected_current:
        raise SupportError(f"线上版本已变化：预期 {args.expected_current}，实际 {current}")
    try:
        if Version(new_version) <= Version(current):
            raise SupportError(f"新版本 {new_version} 必须高于线上版本 {current}")
    except InvalidVersion as exc:
        raise SupportError("脚本版本不是有效 SemVer") from exc
    now = datetime.now(timezone.utc)
    plan = {
        "schema_version": 1,
        "target_origin": client.origin,
        "script_id": int(detail["id"]),
        "script_name": detail.get("name"),
        "current_semantic_version": current,
        "current_platform_version": int(detail["latest_version"]),
        "new_semantic_version": new_version,
        "artifact": str(artifact),
        "artifact_sha256": _sha256(artifact),
        "changelog": args.changelog,
        "created_at": now.isoformat(),
        "expires_at": (now + timedelta(minutes=PLAN_TTL_MINUTES)).isoformat(),
    }
    _write_plan(plan)
    _json_print({
        "action": "publish-plan",
        "target": client.origin,
        "script_id": plan["script_id"],
        "script_name": plan["script_name"],
        "current": current,
        "next": new_version,
        "artifact_sha256": plan["artifact_sha256"],
        "expires_at": plan["expires_at"],
    })


def command_publish_apply(_args) -> None:
    plan = _read_plan()
    try:
        expires = datetime.fromisoformat(str(plan["expires_at"]))
    except (KeyError, ValueError, TypeError) as exc:
        raise SupportError("发布计划有效期无效") from exc
    if datetime.now(timezone.utc) > expires:
        raise SupportError("发布计划已过期，请重新生成")
    client = SupportClient()
    client.authenticate()
    if client.origin != plan.get("target_origin"):
        raise SupportError("当前客户端目标已变化，拒绝发布")
    artifact = Path(str(plan.get("artifact"))).resolve()
    config = _validate_artifact(artifact)
    if _sha256(artifact) != plan.get("artifact_sha256"):
        raise SupportError("发布文件在计划生成后发生变化")
    if str(config.get("version")) != plan.get("new_semantic_version"):
        raise SupportError("发布文件版本与计划不一致")
    detail = client.script_detail(int(plan["script_id"]))
    if (
        str(detail.get("latest_semantic_version")) != plan.get("current_semantic_version")
        or int(detail.get("latest_version")) != int(plan.get("current_platform_version"))
    ):
        raise SupportError("线上版本在计划生成后发生变化")
    with artifact.open("rb") as stream:
        response = client.request(
            "POST",
            f"/api/scripts/{plan['script_id']}/upload-version",
            files={"file": (artifact.name, stream, "application/octet-stream")},
            data={"changelog": plan.get("changelog") or ""},
            timeout=60,
        )
    published = response.json()
    verified = client.script_detail(int(plan["script_id"]))
    if (
        str(verified.get("latest_semantic_version")) != plan.get("new_semantic_version")
        or int(verified.get("latest_version")) != int(plan["current_platform_version"]) + 1
    ):
        raise SupportError("上传完成，但发布后版本复核失败")
    try:
        _plan_path().unlink()
    except FileNotFoundError:
        pass
    _json_print({
        "action": "published",
        "target": client.origin,
        "script_id": published.get("id"),
        "script_name": published.get("name"),
        "platform_version": verified.get("latest_version"),
        "semantic_version": verified.get("latest_semantic_version"),
        "verified": True,
    })


def command_resolve(args) -> None:
    if not args.apply:
        raise SupportError("resolve 是写操作，必须显式提供 --apply")
    client = SupportClient()
    issue = _find_issue(client, args.issue_id)
    if issue.get("status") != "open":
        raise SupportError(f"工单 #{args.issue_id} 当前不是待处理状态")
    client.request(
        "POST",
        f"/api/issues/{args.issue_id}/resolve",
        json={"resolve_note": args.note},
    )
    verified = _find_issue(client, args.issue_id)
    if verified.get("status") != "resolved":
        raise SupportError("工单关闭后复核失败")
    _json_print({
        "target": client.origin,
        "issue_id": args.issue_id,
        "status": "resolved",
        "resolve_note": args.note,
    })


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    target = subparsers.add_parser("target", help="确认当前客户端目标")
    target.set_defaults(func=command_target)

    issues = subparsers.add_parser("issues", help="列出待处理工单")
    issues.set_defaults(func=command_issues)

    issue = subparsers.add_parser("issue", help="查看单个工单、运行和脱敏日志")
    issue.add_argument("--issue-id", type=int, required=True)
    issue.add_argument("--log-lines", type=int, default=120)
    issue.set_defaults(func=command_issue)

    marketplace = subparsers.add_parser("marketplace", help="查询脚本市场版本")
    marketplace.add_argument("--name")
    marketplace.set_defaults(func=command_marketplace)

    download = subparsers.add_parser("download", help="下载服务器当前脚本")
    download.add_argument("--script-id", type=int, required=True)
    download.add_argument("--output", required=True)
    download.add_argument("--overwrite", action="store_true")
    download.set_defaults(func=command_download)

    plan = subparsers.add_parser("publish-plan", help="验证并生成发布计划，不上传")
    plan.add_argument("--artifact", required=True)
    selector = plan.add_mutually_exclusive_group(required=True)
    selector.add_argument("--script-id", type=int)
    selector.add_argument("--name")
    plan.add_argument("--expected-current", required=True)
    plan.add_argument("--changelog", required=True)
    plan.set_defaults(func=command_publish_plan)

    apply = subparsers.add_parser("publish-apply", help="执行未过期的发布计划")
    apply.set_defaults(func=command_publish_apply)

    resolve = subparsers.add_parser("resolve", help="关闭工单")
    resolve.add_argument("--issue-id", type=int, required=True)
    resolve.add_argument("--note", required=True)
    resolve.add_argument("--apply", action="store_true")
    resolve.set_defaults(func=command_resolve)
    return parser


def main() -> int:
    try:
        args = build_parser().parse_args()
        args.func(args)
        return 0
    except SupportError as exc:
        print(f"错误：{redact(str(exc))}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
