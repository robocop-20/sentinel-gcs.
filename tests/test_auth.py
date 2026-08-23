import json
from types import SimpleNamespace

import jwt
import pytest
from argon2 import PasswordHasher

from app.auth import AuthenticationError, AuthManager, ROLE_OPERATOR, ROLE_SERVICE
from app.schemas import Acknowledge


def auth_settings(tmp_path):
    hasher = PasswordHasher()
    signing_key = tmp_path / "jwt-signing-key"
    signing_key.write_text("x" * 64, encoding="utf-8")
    users = tmp_path / "auth-users.json"
    users.write_text(
        json.dumps(
            {
                "users": [
                    {
                        "username": "operator",
                        "secret_hash": hasher.hash("correct-password"),
                        "roles": [ROLE_OPERATOR],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    services = tmp_path / "service-credentials.json"
    services.write_text(
        json.dumps(
            {
                "services": [
                    {
                        "client_id": "vision",
                        "secret_hash": hasher.hash("service-secret"),
                        "roles": [ROLE_SERVICE],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    return SimpleNamespace(
        auth_enabled=True,
        auth_issuer="test-issuer",
        auth_audience="test-audience",
        auth_access_token_minutes=5,
        auth_signing_key_file=str(signing_key),
        auth_users_file=str(users),
        auth_service_credentials_file=str(services),
    )


def test_operator_token_is_short_lived_and_role_restricted(tmp_path):
    manager = AuthManager(auth_settings(tmp_path))
    manager.validate_configuration()
    subject, roles = manager.authenticate_user("operator", "correct-password")
    token = manager.issue_token(subject, roles, "user")
    principal = manager.decode_token(token["access_token"])
    decoded = jwt.decode(token["access_token"], options={"verify_signature": False})
    assert principal.subject == "operator"
    assert principal.roles == frozenset({ROLE_OPERATOR})
    assert decoded["exp"] - decoded["iat"] == 300


def test_service_credentials_cannot_be_used_as_operator(tmp_path):
    manager = AuthManager(auth_settings(tmp_path))
    subject, roles = manager.authenticate_service("vision", "service-secret")
    assert subject == "vision"
    assert roles == frozenset({ROLE_SERVICE})
    with pytest.raises(AuthenticationError):
        manager.authenticate_user("vision", "service-secret")


def test_invalid_password_and_unknown_fields_fail_closed(tmp_path):
    manager = AuthManager(auth_settings(tmp_path))
    with pytest.raises(AuthenticationError):
        manager.authenticate_user("operator", "wrong-password")
    with pytest.raises(ValueError):
        Acknowledge.model_validate({"acknowledged": True, "unexpected": "rejected"})
