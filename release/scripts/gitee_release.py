#!/usr/bin/env python3
"""Create, upload to, and publish a Gitee Release through API v5."""

import argparse
from pathlib import Path
import requests


def _base_url(owner: str, repo: str) -> str:
    return f"https://gitee.com/api/v5/repos/{owner}/{repo}/releases"


def request(method, url, token, **kwargs):
    data = kwargs.pop("data", {})
    data["access_token"] = token
    response = requests.request(method, url, data=data, timeout=120, **kwargs)
    response.raise_for_status()
    return response.json() if response.content else {}


def create_release(owner: str, repo: str, token: str, tag: str, body: str) -> str:
    payload = request(
        "POST",
        _base_url(owner, repo),
        token,
        data={"tag_name": tag, "name": tag, "body": body, "prerelease": "true"},
    )
    release_id = payload.get("id") if isinstance(payload, dict) else None
    if release_id is None or isinstance(release_id, bool) or not str(release_id).isdigit():
        raise RuntimeError("Gitee create response is missing a numeric release id")
    return str(release_id)


def upload_files(owner: str, repo: str, token: str, release_id: str, files) -> None:
    if not str(release_id).isdigit():
        raise ValueError("Gitee release id must be numeric")
    for path in files:
        with path.open("rb") as stream:
            request(
                "POST",
                f"{_base_url(owner, repo)}/{release_id}/attach_files",
                token,
                files={"file": (path.name, stream)},
            )


def publish_release(
    owner: str,
    repo: str,
    token: str,
    release_id: str,
    prerelease: bool = False,
) -> None:
    if not str(release_id).isdigit():
        raise ValueError("Gitee release id must be numeric")
    request(
        "PATCH",
        f"{_base_url(owner, repo)}/{release_id}",
        token,
        data={"prerelease": "true" if prerelease else "false"},
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
    parser.add_argument("--prerelease", choices=["true", "false"], default="false")
    parser.add_argument("--file", type=Path, action="append", default=[])
    parser.add_argument("--body", default="AutoScript Hub release")
    args = parser.parse_args()
    if args.command == "create":
        if not args.tag:
            parser.error("create requires --tag")
        print(create_release(args.owner, args.repo, args.token, args.tag, args.body))
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
