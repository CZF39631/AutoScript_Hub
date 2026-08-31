"""Optional external identity authentication and local-user provisioning."""

from dataclasses import dataclass
import secrets
from typing import Any

import httpx
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import config
from app.auth import hash_password
from app.models import User


class ExternalAuthError(RuntimeError):
    """Base error safe for the login router to classify."""


class InvalidExternalCredentials(ExternalAuthError):
    pass


class ExternalAuthUnavailable(ExternalAuthError):
    pass


class InvalidExternalResponse(ExternalAuthError):
    pass


class ExternalIdentityNotAuthorized(ExternalAuthError):
    pass


@dataclass(frozen=True)
class ExternalIdentity:
    subject: str
    username: str
    display_name: str
    role: str


def _read_path(payload: Any, path: str) -> Any:
    value = payload
    for part in path.split("."):
        if not isinstance(value, dict) or part not in value:
            raise InvalidExternalResponse(f"Missing configured response field: {path}")
        value = value[part]
    return value


def authenticate(username: str, password: str) -> ExternalIdentity:
    """Authenticate against the configured generic HTTP endpoint."""
    fields = {
        config.EXTERNAL_AUTH_USERNAME_FIELD: username,
        config.EXTERNAL_AUTH_PASSWORD_FIELD: password,
    }
    request_kwargs = {"data": fields} if config.EXTERNAL_AUTH_METHOD == "http_form" else {"json": fields}
    try:
        response = httpx.post(
            config.EXTERNAL_AUTH_URL,
            timeout=config.EXTERNAL_AUTH_TIMEOUT_SECONDS,
            verify=config.EXTERNAL_AUTH_VERIFY_TLS,
            follow_redirects=False,
            **request_kwargs,
        )
    except httpx.RequestError as exc:
        raise ExternalAuthUnavailable("External authentication service is unavailable") from exc

    if response.status_code in {400, 401, 403}:
        raise InvalidExternalCredentials("Invalid username or password")
    if response.status_code < 200 or response.status_code >= 300:
        raise ExternalAuthUnavailable("External authentication service returned an error")
    try:
        payload = response.json()
    except ValueError as exc:
        raise InvalidExternalResponse("External authentication response is not JSON") from exc

    if config.EXTERNAL_AUTH_SUCCESS_PATH and _read_path(payload, config.EXTERNAL_AUTH_SUCCESS_PATH) is not True:
        raise InvalidExternalCredentials("Invalid username or password")

    subject = str(_read_path(payload, config.EXTERNAL_AUTH_SUBJECT_PATH)).strip()
    external_username = str(_read_path(payload, config.EXTERNAL_AUTH_USERNAME_PATH)).strip()
    display_name = str(_read_path(payload, config.EXTERNAL_AUTH_DISPLAY_NAME_PATH)).strip()
    external_role = str(_read_path(payload, config.EXTERNAL_AUTH_ROLE_PATH)).strip()
    local_role = config.EXTERNAL_AUTH_ROLE_MAP.get(external_role)
    if not local_role:
        raise ExternalIdentityNotAuthorized("External role is not mapped")
    if not subject or not external_username or len(subject) > 255 or len(external_username) > 50:
        raise InvalidExternalResponse("External identity fields are invalid")
    if not display_name:
        display_name = external_username
    return ExternalIdentity(subject, external_username, display_name[:100], str(local_role))


def resolve_local_user(db: Session, identity: ExternalIdentity) -> User:
    """Find or provision a local authorization record for an external identity."""
    user = db.query(User).filter(
        User.auth_source == "external",
        User.external_subject == identity.subject,
        User.is_deleted == False,
    ).first()
    if user:
        user.display_name = identity.display_name
        # Authentication is external, but authorization is managed locally.
        # Keep administrator-assigned roles stable across later logins.
        return user

    # Never bind an external identity to an existing local/same-name account.
    if db.query(User).filter(User.username == identity.username).first():
        raise ExternalIdentityNotAuthorized("External username conflicts with a local account")

    user = User(
        username=identity.username,
        password_hash=hash_password(secrets.token_urlsafe(48)),
        display_name=identity.display_name,
        role=identity.role,
        status="active",
        auth_source="external",
        external_subject=identity.subject,
    )
    db.add(user)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise ExternalIdentityNotAuthorized("External identity could not be provisioned") from exc
    return user
