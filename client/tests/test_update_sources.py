from client.update.sources import DirectManifestSource, GitHubReleaseSource


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


def test_github_source_resolves_release_assets():
    api = "https://api.github.com/repos/acme/hub/releases"
    responses = {
        api: b'''[{"draft":false,"prerelease":true,"assets":[
          {"name":"autoscript-hub-update.json","browser_download_url":"https://github.example/manifest"},
          {"name":"autoscript-hub-update.json.sig","browser_download_url":"https://github.example/signature"}
        ]}]''',
        "https://github.example/manifest": b"manifest",
        "https://github.example/signature": b"signature",
    }
    source = GitHubReleaseSource("acme/hub", channel="beta", http_get=responses.__getitem__)

    assert source.fetch() == (b"manifest", b"signature")


def test_github_beta_source_skips_newer_stable_release():
    api = "https://api.github.com/repos/acme/hub/releases"
    responses = {
        api: b'''[
          {"draft":false,"prerelease":false,"assets":[
            {"name":"autoscript-hub-update.json","browser_download_url":"https://github.example/stable-manifest"},
            {"name":"autoscript-hub-update.json.sig","browser_download_url":"https://github.example/stable-signature"}
          ]},
          {"draft":false,"prerelease":true,"assets":[
            {"name":"autoscript-hub-update.json","browser_download_url":"https://github.example/beta-manifest"},
            {"name":"autoscript-hub-update.json.sig","browser_download_url":"https://github.example/beta-signature"}
          ]}
        ]''',
        "https://github.example/stable-manifest": b"stable-manifest",
        "https://github.example/stable-signature": b"stable-signature",
        "https://github.example/beta-manifest": b"beta-manifest",
        "https://github.example/beta-signature": b"beta-signature",
    }
    source = GitHubReleaseSource("acme/hub", channel="beta", http_get=responses.__getitem__)

    assert source.fetch() == (b"beta-manifest", b"beta-signature")
