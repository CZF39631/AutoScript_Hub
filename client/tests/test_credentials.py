import os

import pytest


def test_credential_round_trip_uses_encrypted_store(monkeypatch, tmp_path):
    from client.runtime import credentials

    credential_file = tmp_path / "credentials.json"
    monkeypatch.setattr(credentials, "_CREDENTIAL_FILE", credential_file)
    monkeypatch.setattr(credentials, "_crypt_protect", lambda value: b"encrypted:" + value[::-1])
    monkeypatch.setattr(
        credentials,
        "_crypt_unprotect",
        lambda value: value.removeprefix(b"encrypted:")[::-1],
    )

    credentials.save_credentials("https://server.example/", "User", "secret-password")

    assert "secret-password" not in credential_file.read_text(encoding="utf-8")
    assert credentials.load_credentials("https://server.example", "user") == "secret-password"

    credentials.delete_credentials("https://server.example", "USER")
    assert not credential_file.exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows DPAPI only")
def test_windows_dpapi_round_trip(monkeypatch, tmp_path):
    from client.runtime import credentials

    monkeypatch.setattr(credentials, "_CREDENTIAL_FILE", tmp_path / "credentials.json")
    password = "复杂密码🔐\x00结尾"
    credentials.save_credentials("https://server.example", "测试用户", password)
    assert credentials.load_credentials("https://server.example", "测试用户") == password


def test_invalid_credential_blob_is_ignored(monkeypatch, tmp_path):
    from client.runtime import credentials

    credential_file = tmp_path / "credentials.json"
    credential_file.write_text('{"https://server.example\\nuser":"not-base64!"}', encoding="utf-8")
    monkeypatch.setattr(credentials, "_CREDENTIAL_FILE", credential_file)

    assert credentials.load_credentials("https://server.example", "user") == ""
