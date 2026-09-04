from client.agent.updater import _sources
from client.update.sources import DirectManifestSource, GiteeReleaseSource, GitHubReleaseSource


def test_default_update_check_uses_gitee_without_querying_github():
    sources = _sources({
        "gitee_update_repository": "chuzifeng/auto-script_-hub",
        "github_update_repository": "CZF39631/AutoScript_Hub",
        "update_channel": "stable",
        "update_manifest_urls": [],
    })

    assert [type(source) for source in sources] == [GiteeReleaseSource]


def test_direct_source_reads_manifest_and_signature():
    responses = {
        "https://mirror.example/autoscript-hub-update.json": b"manifest",
        "https://mirror.example/autoscript-hub-update.json.sig": b"signature",
    }
    source = DirectManifestSource(
        "https://mirror.example/autoscript-hub-update.json",
        http_get=responses.__getitem__,
    )

    assert source.fetch() == (b"manifest", b"signature")


def test_gitee_source_resolves_release_assets():
    api = "https://gitee.com/api/v5/repos/acme/hub/releases?page=1&per_page=100"
    responses = {
        api: b'''[{"tag_name":"v1.2.0","prerelease":false,"assets":[
          {"name":"autoscript-hub-update.json","browser_download_url":"https://gitee.example/manifest"},
          {"name":"autoscript-hub-update.json.sig","browser_download_url":"https://gitee.example/signature"}
        ]}]''',
        "https://gitee.example/manifest": b"manifest",
        "https://gitee.example/signature": b"signature",
    }
    source = GiteeReleaseSource("acme/hub", channel="stable", http_get=responses.__getitem__)

    assert source.fetch() == (b"manifest", b"signature")


def test_github_source_resolves_release_assets():
    api = "https://api.github.com/repos/acme/hub/releases?per_page=100"
    responses = {
        api: b'''[{"tag_name":"v1.2.0-beta.1","draft":false,"prerelease":true,"assets":[
          {"name":"autoscript-hub-update.json","browser_download_url":"https://github.example/manifest"},
          {"name":"autoscript-hub-update.json.sig","browser_download_url":"https://github.example/signature"}
        ]}]''',
        "https://github.example/manifest": b"manifest",
        "https://github.example/signature": b"signature",
    }
    source = GitHubReleaseSource("acme/hub", channel="beta", http_get=responses.__getitem__)

    assert source.fetch() == (b"manifest", b"signature")


def test_release_source_selects_highest_semver_instead_of_api_order():
    api = "https://api.github.com/repos/acme/hub/releases?per_page=100"
    responses = {
        api: b'''[
          {"tag_name":"v1.1.0","draft":false,"prerelease":false,"assets":[
            {"name":"autoscript-hub-update.json","browser_download_url":"https://github.example/old"},
            {"name":"autoscript-hub-update.json.sig","browser_download_url":"https://github.example/old.sig"}
          ]},
          {"tag_name":"v1.10.0","draft":false,"prerelease":false,"assets":[
            {"name":"autoscript-hub-update.json","browser_download_url":"https://github.example/latest"},
            {"name":"autoscript-hub-update.json.sig","browser_download_url":"https://github.example/latest.sig"}
          ]}
        ]''',
        "https://github.example/old": b"old",
        "https://github.example/old.sig": b"old-signature",
        "https://github.example/latest": b"latest",
        "https://github.example/latest.sig": b"latest-signature",
    }
    source = GitHubReleaseSource("acme/hub", channel="stable", http_get=responses.__getitem__)

    assert source.fetch() == (b"latest", b"latest-signature")


def test_beta_channel_can_receive_a_stable_release():
    api = "https://api.github.com/repos/acme/hub/releases?per_page=100"
    responses = {
        api: b'''[
          {"tag_name":"v1.2.0-beta.1","draft":false,"prerelease":true,"assets":[
            {"name":"autoscript-hub-update.json","browser_download_url":"https://github.example/beta"},
            {"name":"autoscript-hub-update.json.sig","browser_download_url":"https://github.example/beta.sig"}
          ]},
          {"tag_name":"v1.2.0","draft":false,"prerelease":false,"assets":[
            {"name":"autoscript-hub-update.json","browser_download_url":"https://github.example/stable"},
            {"name":"autoscript-hub-update.json.sig","browser_download_url":"https://github.example/stable.sig"}
          ]}
        ]''',
        "https://github.example/beta": b"beta",
        "https://github.example/beta.sig": b"beta-signature",
        "https://github.example/stable": b"stable",
        "https://github.example/stable.sig": b"stable-signature",
    }
    source = GitHubReleaseSource("acme/hub", channel="beta", http_get=responses.__getitem__)

    assert source.fetch() == (b"stable", b"stable-signature")
