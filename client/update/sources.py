"""Anonymous GitHub Release and direct-manifest update sources."""

import json
from typing import Callable, Optional
from urllib.request import Request, urlopen


def http_get_bytes(url: str) -> bytes:
    request = Request(url, headers={"User-Agent": "AutoScript-Hub-Updater/0.9"})
    with urlopen(request, timeout=30) as response:
        return response.read()


class DirectManifestSource:
    def __init__(self, manifest_url: str, http_get: Callable[[str], bytes] = http_get_bytes):
        self.manifest_url = manifest_url
        self.http_get = http_get

    def fetch(self) -> tuple[bytes, bytes]:
        return self.http_get(self.manifest_url), self.http_get(self.manifest_url + ".sig")


class GitHubReleaseSource:
    def __init__(
        self,
        repository: str,
        channel: str = "beta",
        http_get: Callable[[str], bytes] = http_get_bytes,
    ):
        if channel not in {"beta", "stable"}:
            raise ValueError("GitHub 更新通道必须是 beta 或 stable")
        self.repository = repository
        self.channel = channel
        self.http_get = http_get

    def fetch(self) -> tuple[bytes, bytes]:
        api_url = f"https://api.github.com/repos/{self.repository}/releases"
        releases = json.loads(self.http_get(api_url).decode("utf-8"))
        for release in releases:
            if release.get("draft"):
                continue
            if self.channel == "beta" and not release.get("prerelease"):
                continue
            if self.channel == "stable" and release.get("prerelease"):
                continue
            assets = {item.get("name"): item.get("browser_download_url") for item in release.get("assets", [])}
            manifest_url = assets.get("autoscript-hub-update.json")
            signature_url = assets.get("autoscript-hub-update.json.sig")
            if manifest_url and signature_url:
                return self.http_get(manifest_url), self.http_get(signature_url)
        raise LookupError(f"GitHub 没有 {self.channel} 通道的签名更新清单")
