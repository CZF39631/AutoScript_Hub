import pytest

from app import config


def test_lan_server_rejects_default_secrets(monkeypatch):
    monkeypatch.setattr(config, "BACKEND_HOST", "0.0.0.0")
    monkeypatch.setattr(config, "JWT_SECRET", "autoscript-dev-secret-change-in-prod")
    monkeypatch.setattr(config, "ADMIN_PASSWORD", "admin123")
    with pytest.raises(RuntimeError, match="JWT_SECRET"):
        config.validate_security_config()


def test_lan_server_rejects_default_admin_password(monkeypatch):
    monkeypatch.setattr(config, "BACKEND_HOST", "0.0.0.0")
    monkeypatch.setattr(config, "JWT_SECRET", "a-unique-secret-that-is-longer-than-32-characters")
    monkeypatch.setattr(config, "ADMIN_PASSWORD", "CHANGE_ME_BEFORE_FIRST_START")
    with pytest.raises(RuntimeError, match="ADMIN_PASSWORD"):
        config.validate_security_config()


def test_lan_server_accepts_strong_credentials(monkeypatch):
    monkeypatch.setattr(config, "BACKEND_HOST", "0.0.0.0")
    monkeypatch.setattr(config, "JWT_SECRET", "a-unique-secret-that-is-longer-than-32-characters")
    monkeypatch.setattr(config, "ADMIN_PASSWORD", "strong-admin-password")
    config.validate_security_config()
