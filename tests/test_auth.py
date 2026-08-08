from __future__ import annotations

from datetime import datetime, timedelta, timezone
import sys
from pathlib import Path
from typing import Any
from uuid import UUID

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import rate_ingest.auth as auth_module
from rate_ingest.api import app
from rate_ingest.auth import AuthenticationError, SupabaseTokenVerifier
from rate_ingest.config import Settings


SUPABASE_URL = "https://test-project.supabase.co"
ISSUER = f"{SUPABASE_URL}/auth/v1"
USER_ID = UUID("123e4567-e89b-12d3-a456-426614174000")


class FixedJWKClient:
    def __init__(self, signing_key: jwt.PyJWK) -> None:
        self.signing_key = signing_key

    def get_signing_key_from_jwt(self, token: str) -> jwt.PyJWK:
        return self.signing_key


@pytest.fixture
def token_tools():
    private_key = ec.generate_private_key(ec.SECP256R1())
    public_jwk = jwt.algorithms.ECAlgorithm.to_jwk(
        private_key.public_key(),
        as_dict=True,
    )
    public_jwk.update({"kid": "test-key", "alg": "ES256", "use": "sig"})
    verifier = SupabaseTokenVerifier(
        SUPABASE_URL,
        jwks_client=FixedJWKClient(jwt.PyJWK.from_dict(public_jwk)),
    )

    def make_token(**overrides: Any) -> str:
        now = datetime.now(timezone.utc)
        claims: dict[str, Any] = {
            "iss": ISSUER,
            "aud": "authenticated",
            "exp": now + timedelta(minutes=5),
            "iat": now,
            "sub": str(USER_ID),
            "role": "authenticated",
            "email": "operator@example.com",
        }
        claims.update(overrides)
        return jwt.encode(
            claims,
            private_key,
            algorithm="ES256",
            headers={"kid": "test-key"},
        )

    return verifier, make_token


def test_settings_loads_supabase_values_and_auth_flag(tmp_path, monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", SUPABASE_URL)
    monkeypatch.setenv("SUPABASE_PUBLISHABLE_KEY", "test-publishable-key")
    monkeypatch.setenv("SUPABASE_DB_URL", "postgresql://server-only")
    monkeypatch.setenv("AUTH_REQUIRED", "false")

    settings = Settings.load(cwd=tmp_path)

    assert settings.supabase_url == SUPABASE_URL
    assert settings.supabase_publishable_key == "test-publishable-key"
    assert settings.supabase_db_url == "postgresql://server-only"
    assert settings.auth_required is False


def test_verifier_accepts_valid_token(token_tools):
    verifier, make_token = token_tools

    user = verifier.verify(make_token())

    assert user.user_id == USER_ID
    assert user.email == "operator@example.com"
    assert user.claims["role"] == "authenticated"


@pytest.mark.parametrize(
    ("claim", "value"),
    [
        ("iss", "https://other-project.supabase.co/auth/v1"),
        ("aud", "anon"),
        ("role", "anon"),
    ],
)
def test_verifier_rejects_wrong_project_or_user_claim(token_tools, claim, value):
    verifier, make_token = token_tools

    with pytest.raises(AuthenticationError):
        verifier.verify(make_token(**{claim: value}))


def test_verifier_rejects_expired_token(token_tools):
    verifier, make_token = token_tools
    expired = datetime.now(timezone.utc) - timedelta(minutes=1)

    with pytest.raises(AuthenticationError):
        verifier.verify(make_token(exp=expired))


def test_verifier_rejects_invalid_token(token_tools):
    verifier, _ = token_tools

    with pytest.raises(AuthenticationError):
        verifier.verify("not-a-jwt")


def test_api_me_requires_authorization_header():
    response = TestClient(app).get("/api/me")

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


@pytest.mark.parametrize(
    "authorization",
    ["Basic abc", "Bearer", "Bearer abc extra"],
)
def test_api_me_rejects_malformed_authorization_header(authorization):
    response = TestClient(app).get(
        "/api/me",
        headers={"Authorization": authorization},
    )

    assert response.status_code == 401


def test_api_me_rejects_invalid_and_expired_jwts(token_tools, monkeypatch):
    verifier, make_token = token_tools
    monkeypatch.setattr(auth_module, "get_token_verifier", lambda: verifier)
    client = TestClient(app)

    invalid_response = client.get(
        "/api/me",
        headers={"Authorization": "Bearer not-a-jwt"},
    )
    expired_response = client.get(
        "/api/me",
        headers={
            "Authorization": (
                "Bearer "
                + make_token(
                    exp=datetime.now(timezone.utc) - timedelta(minutes=1)
                )
            )
        },
    )

    assert invalid_response.status_code == 401
    assert expired_response.status_code == 401


def test_api_me_returns_valid_user(token_tools, monkeypatch):
    verifier, make_token = token_tools
    monkeypatch.setattr(auth_module, "get_token_verifier", lambda: verifier)

    response = TestClient(app).get(
        "/api/me",
        headers={"Authorization": f"Bearer {make_token()}"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "user_id": str(USER_ID),
        "email": "operator@example.com",
        "organizations": [],
    }


def test_stage_one_keeps_existing_routes_public(tmp_path, monkeypatch):
    monkeypatch.setenv("RATE_INGEST_ROOT", str(tmp_path))
    monkeypatch.setenv("AUTH_REQUIRED", "false")
    client = TestClient(app)

    assert client.get("/api/health").status_code == 200
    assert client.get("/api/imports").status_code == 200
