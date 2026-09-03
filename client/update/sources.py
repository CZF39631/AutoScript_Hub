"""Anonymous Gitee/GitHub Release and direct-manifest update sources."""

import json
from typing import Callable
from urllib.request import Request, urlopen

from packaging.version import InvalidVersion, Version


MANIFEST_NAME = "autoscript-hub-update.json"
SIGNATURE_NAME = MANIFEST_NAME + ".sig"


def http_get_bytes(url: str) -> bytes:
    request = Request(url, headers={"User-Agent": "AutoScript-Hub-Updater/1.0"})
    with urlopen(request, timeout=30) as response:
        return response.read()


def _release_version(release: dict):
    tag = str(release.get("tag_name", "")).strip().lstrip("v")
    try:
        return Version(tag)
    except InvalidVersion:
        return None


def _release_candidates(releases, channel: str):
    if not isinstance(releases, list):
        raise ValueError("发行版接口返回格式无效")
    candidates = []
    for release in releases:
        if not isinstance(release, dict) or release.get("draft"):
            continue
        # Beta users may receive stable releases; stable users never receive prereleases.
        if channel == "stable" and release.get("prerelease"):
            continue
        version = _release_version(release)
        if version is not None:
            candidates.append((version, release))
    return [release for _, release in sorted(candidates, key=lambda item: item[0], reverse=True)]


def _asset_urls(release: dict):
    assets = {
        item.get("name"): item.get("browser_download_url")
        for item in release.get("assets", [])
        if isinstance(item, dict)
    }
    return assets.get(MANIFEST_NAME), assets.get(SIGNATURE_NAME)


class DirectManifestSource:
    def __init__(self, manifest_url: str, http_get: Callable[[str], bytes] = http_get_bytes):
        self.manifest_url = manifest_url
        self.http_get = http_get

    def fetch(self) -> tuple[bytes, bytes]:
        return self.http_get(self.manifest_url), self.http_get(self.manifest_url + ".sig")


class ReleaseSource:
    host_name = "发行版"

    def __init__(
        self,
        repository: str,
        channel: str = "stable",
        http_get: Callable[[str], bytes] = http_get_bytes,
    ):
        if channel not in {"beta", "stable"}:
            raise ValueError("更新通道必须是 beta 或 stable")
        self.repository = repository
        self.channel = channel
        self.http_get = http_get

    @property
    def api_url(self):
        raise NotImplementedError

    def fetch(self) -> tuple[bytes, bytes]:
        releases = json.loads(self.http_get(self.api_url).decode("utf-8"))
        for release in _release_candidates(releases, self.channel):
            manifest_url, signature_url = _asset_urls(release)
            if manifest_url and signature_url:
                return self.http_get(manifest_url), self.http_get(signature_url)
        raise LookupError(f"{self.host_name} 没有 {self.channel} 通道的签名更新清单")


class GiteeReleaseSource(ReleaseSource):
    host_name = "Gitee"

    @property
    def api_url(self):
        return f"https://gitee.com/api/v5/repos/{self.repository}/releases?page=1&per_page=100"


class GitHubReleaseSource(ReleaseSource):
    host_name = "GitHub"

    @property
    def api_url(self):
        return f"https://api.github.com/repos/{self.repository}/releases?per_page=100"
