"""Local OAuth2 credential verification and short-lived JWT issuance.

Credential files contain only Argon2id password/secret hashes.  The JWT
signing key is mounted separately and is never returned by an API route.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable
from uuid import uuid4

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from .config import Settings


ROLE_VIEWER = "viewer"
ROLE_OPERATOR = "operator"
ROLE_ANALYST = "analyst"
ROLE_AUDITOR = "auditor"
ROLE_ADMINISTRATOR = "administrator"
ROLE_SYSTEM_ADMIN = "system-admin"
ROLE_SERVICE = "service"
KNOWN_ROLES = {
    ROLE_VIEWER,
    ROLE_OPERATOR,
    ROLE_ANALYST,
    ROLE_AUDITOR,
    ROLE_ADMINISTRATOR,
    ROLE_SYSTEM_ADMIN,
    ROLE_SERVICE,
}


class AuthenticationError(ValueError):
    """A deliberately non-specific authentication failure."""


@dataclass(frozen=True)
class Principal:
    subject: str
    roles: frozenset[str]
    kind: str
    token_id: str

    def permits(self, required: Iterable[str]) -> bool:
        needed = set(required)
        return bool(
            {ROLE_SYSTEM_ADMIN, ROLE_ADMINISTRATOR}.intersection(self.roles)
            or self.roles.intersection(needed)
        )


class AuthManager:
    def __init__(self, settings: Settings) -> None:
        self.enabled = settings.auth_enabled
        self.issuer = settings.auth_issuer
        self.audience = settings.auth_audience
        self.token_seconds = max(60, settings.auth_access_token_minutes * 60)
        self._signing_key_file = Path(settings.auth_signing_key_file)
        self._users_file = Path(settings.auth_users_file)
        self._services_file = Path(settings.auth_service_credentials_file)
        self._password_hasher = PasswordHasher()

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise AuthenticationError(
                "Authentication configuration is unavailable"
            ) from exc
        if not isinstance(payload, dict):
            raise AuthenticationError("Authentication configuration is invalid")
        return payload

    def _signing_key(self) -> str:
        try:
            key = self._signing_key_file.read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise AuthenticationError("JWT signing key is unavailable") from exc
        if len(key.encode("utf-8")) < 32:
            raise AuthenticationError("JWT signing key must contain at least 32 bytes")
        return key

    def validate_configuration(self) -> None:
        if not self.enabled:
            return
        self._signing_key()
        users = self._read_json(self._users_file).get("users")
        services = self._read_json(self._services_file).get("services")
        if not isinstance(users, list) or not users:
            raise AuthenticationError("At least one operator account is required")
        if not isinstance(services, list) or not services:
            raise AuthenticationError("At least one service account is required")

    def _verify_entry(
        self, entries: object, identifier_key: str, identifier: str, secret: str
    ) -> dict[str, Any]:
        if not isinstance(entries, list):
            raise AuthenticationError("Invalid credentials")
        entry = next(
            (
                item
                for item in entries
                if isinstance(item, dict) and item.get(identifier_key) == identifier
            ),
            None,
        )
        if (
            not entry
            or entry.get("disabled") is True
            or not isinstance(entry.get("secret_hash"), str)
        ):
            raise AuthenticationError("Invalid credentials")
        try:
            self._password_hasher.verify(entry["secret_hash"], secret)
        except (InvalidHashError, VerificationError, VerifyMismatchError) as exc:
            raise AuthenticationError("Invalid credentials") from exc
        roles = entry.get("roles", [])
        if (
            not isinstance(roles, list)
            or not roles
            or not set(roles).issubset(KNOWN_ROLES)
        ):
            raise AuthenticationError("Invalid account role configuration")
        return entry

    def authenticate_user(
        self, username: str, password: str
    ) -> tuple[str, frozenset[str]]:
        data = self._read_json(self._users_file)
        entry = self._verify_entry(data.get("users"), "username", username, password)
        roles = frozenset(str(role) for role in entry["roles"] if role != ROLE_SERVICE)
        if not roles:
            raise AuthenticationError("Invalid account role configuration")
        return username, roles

    def authenticate_service(
        self, client_id: str, client_secret: str
    ) -> tuple[str, frozenset[str]]:
        data = self._read_json(self._services_file)
        entry = self._verify_entry(
            data.get("services"), "client_id", client_id, client_secret
        )
        if ROLE_SERVICE not in entry["roles"]:
            raise AuthenticationError("Invalid account role configuration")
        return client_id, frozenset({ROLE_SERVICE})

    def issue_token(
        self, subject: str, roles: Iterable[str], kind: str
    ) -> dict[str, Any]:
        now = int(time.time())
        expires_at = now + self.token_seconds
        claims = {
            "iss": self.issuer,
            "aud": self.audience,
            "sub": subject,
            "roles": sorted(set(roles)),
            "kind": kind,
            "iat": now,
            "nbf": now,
            "exp": expires_at,
            "jti": str(uuid4()),
        }
        encoded = jwt.encode(claims, self._signing_key(), algorithm="HS256")
        return {
            "access_token": encoded,
            "token_type": "bearer",
            "expires_in": self.token_seconds,
            "roles": claims["roles"],
        }

    def decode_token(self, token: str) -> Principal:
        try:
            claims = jwt.decode(
                token,
                self._signing_key(),
                algorithms=["HS256"],
                audience=self.audience,
                issuer=self.issuer,
                options={"require": ["exp", "iat", "nbf", "sub", "iss", "aud", "jti"]},
            )
        except jwt.PyJWTError as exc:
            raise AuthenticationError("Invalid or expired access token") from exc
        roles = claims.get("roles")
        if (
            not isinstance(roles, list)
            or not roles
            or not set(roles).issubset(KNOWN_ROLES)
        ):
            raise AuthenticationError("Invalid access token roles")
        kind = claims.get("kind")
        if kind not in {"user", "service"}:
            raise AuthenticationError("Invalid access token subject type")
        return Principal(str(claims["sub"]), frozenset(roles), kind, str(claims["jti"]))
