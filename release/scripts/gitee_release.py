#!/usr/bin/env python3
"""Create, upload to, and publish a Gitee Release through API v5."""

import argparse
from pathlib import Path
import time
import requests


def _base_url(owner: str, repo: str) -> str:
    return f"https://gitee.com/api/v5/repos/{owner}/{repo}/releases"


def request(method, url, token, **kwargs):
    timeout = kwargs.pop("timeout", 120)
    if method.upper() == "GET":
        params = kwargs.pop("params", {})
        params["access_token"] = token
        response = requests.request(method, url, params=params, timeout=timeout, **kwargs)
    else:
        data = kwargs.pop("data", {})
        data["access_token"] = token
        response = requests.request(method, url, data=data, timeout=timeout, **kwargs)
    try:
        response.raise_for_status()
    except requests.HTTPError as exc:
        detail = getattr(response, "text", "")[:500].replace(token, "***")
        raise RuntimeError(f"Gitee API {response.status_code}: {detail}") from exc
    return response.json() if response.content else {}


def create_release(
    owner: str,
    repo: str,
    token: str,
    tag: str,
    body: str,
    target_commitish: str,
) -> str:
    payload = request(
        "POST",
        _base_url(owner, repo),
        token,
        data={
            "tag_name": tag,
            "name": tag,
            "body": body,
            "target_commitish": target_commitish,
            "prerelease": "true",
        },
    )
    release_id = payload.get("id") if isinstance(payload, dict) else None
    if release_id is None or isinstance(release_id, bool) or not str(release_id).isdigit():
        raise RuntimeError("Gitee create response is missing a numeric release id")
    return str(release_id)


def _uploaded_asset_names(owner: str, repo: str, token: str, release_id: str) -> set[str]:
    payload = request("GET", f"{_base_url(owner, repo)}/{release_id}", token, timeout=60)
    if not isinstance(payload, dict):
        return set()
    assets = payload.get("assets", [])
    return {
        item.get("name")
        for item in assets
        if isinstance(item, dict) and isinstance(item.get("name"), str)
    }


def upload_files(
    owner: str,
    repo: str,
    token: str,
    release_id: str,
    files,
    *,
    attempts: int = 3,
    retry_delay: float = 2,
) -> None:
    if not str(release_id).isdigit():
        raise ValueError("Gitee release id must be numeric")
    if attempts < 1:
        raise ValueError("upload attempts must be positive")
    upload_url = f"{_base_url(owner, repo)}/{release_id}/attach_files"
    for path in files:
        if path.name in _uploaded_asset_names(owner, repo, token, release_id):
            continue
        last_error = None
        for attempt in range(attempts):
            try:
                # 每次重试都重新打开文件，避免从上次中断位置继续提交损坏附件。
                with path.open("rb") as stream:
                    request(
                        "POST",
                        upload_url,
                        token,
                        files={"file": (path.name, stream)},
                        timeout=180,
                    )
                break
            except Exception as exc:
                last_error = exc
                # 上传可能已被 Gitee 接收、但响应在返回途中丢失；先查询再决定是否重传。
                try:
                    if path.name in _uploaded_asset_names(owner, repo, token, release_id):
                        break
                except Exception:
                    pass
                if attempt + 1 == attempts:
                    raise RuntimeError(f"Gitee 附件上传失败（{path.name}，已重试 {attempts} 次）") from last_error
                time.sleep(retry_delay * (2 ** attempt))


def publish_release(
    owner: str,
    repo: str,
    token: str,
    release_id: str,
    prerelease: bool = False,
) -> None:
    if not str(release_id).isdigit():
        raise ValueError("Gitee release id must be numeric")
    url = f"{_base_url(owner, repo)}/{release_id}"
    current = request("GET", url, token)
    if not isinstance(current, dict) or not current.get("tag_name") or not current.get("name"):
        raise RuntimeError("Gitee release response is missing tag_name or name")
    request(
        "PATCH",
        url,
        token,
        data={
            "tag_name": current["tag_name"],
            "name": current["name"],
            "body": current.get("body") or "AutoScript Hub release",
            "prerelease": "true" if prerelease else "false",
        },
    )


def delete_release(owner: str, repo: str, token: str, release_id: str) -> None:
    if not str(release_id).isdigit():
        raise ValueError("Gitee release id must be numeric")
    request(
        "DELETE",
        f"{_base_url(owner, repo)}/{release_id}",
        token,
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["create", "upload", "publish", "delete"])
    parser.add_argument("--owner", required=True)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--token", required=True)
    parser.add_argument("--tag")
    parser.add_argument("--release-id")
    parser.add_argument("--target-commitish")
    parser.add_argument("--prerelease", choices=["true", "false"], default="false")
    parser.add_argument("--file", type=Path, action="append", default=[])
    parser.add_argument("--body", default="AutoScript Hub release")
    args = parser.parse_args()
    if args.command == "create":
        if not args.tag or not args.target_commitish:
            parser.error("create requires --tag and --target-commitish")
        print(
            create_release(
                args.owner,
                args.repo,
                args.token,
                args.tag,
                args.body,
                args.target_commitish,
            )
        )
    elif args.command == "upload":
        if not args.release_id:
            parser.error("upload requires --release-id")
        upload_files(args.owner, args.repo, args.token, args.release_id, args.file)
    elif args.command == "publish":
        if not args.release_id:
            parser.error("publish requires --release-id")
        publish_release(
            args.owner,
            args.repo,
            args.token,
            args.release_id,
            prerelease=args.prerelease == "true",
        )
    else:
        if not args.release_id:
            parser.error("delete requires --release-id")
        delete_release(args.owner, args.repo, args.token, args.release_id)


if __name__ == "__main__":
    main()
