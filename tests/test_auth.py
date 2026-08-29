from __future__ import annotations

from datetime import datetime, timedelta, timezone
import sys
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import rate_ingest.auth as auth_module
from rate_ingest.api import app
from rate_ingest.auth import (
    AuthenticationError,
    OrganizationMembership,
    RequestContext,
    SupabaseMembershipResolver,
    SupabaseTokenVerifier,
    require_operator,
)
from rate_ingest.config import Settings


SUPABASE_URL = "https://test-project.supabase.co"
ISSUER = f"{SUPABASE_URL}/auth/v1"
USER_ID = UUID("123e4567-e89b-12d3-a456-426614174000")
ORGANIZATION_ID = UUID("123e4567-e89b-12d3-a456-426614174001")


class FixedJWKClient:
    def __init__(self, signing_key: jwt.PyJWK) -> None:
        self.signing_key = signing_key

    def get_signing_key_from_jwt(self, token: str) -> jwt.PyJWK:
        return self.signing_key


class FixedMembershipResolver:
    def __init__(self, memberships: tuple[OrganizationMembership, ...]) -> None:
        self.memberships = memberships

    def resolve(self, _user):
        return self.memberships


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


def membership(role: str = "operator") -> OrganizationMembership:
    return OrganizationMembership(
        organization_id=ORGANIZATION_ID,
        organization_name="Reudan",
        organization_slug="reudan",
        role=role,
    )


def use_auth(
    monkeypatch,
    verifier: SupabaseTokenVerifier,
    memberships: tuple[OrganizationMembership, ...],
) -> None:
    monkeypatch.setattr(auth_module, "get_token_verifier", lambda: verifier)
    monkeypatch.setattr(
        auth_module,
        "get_membership_resolver",
        lambda: FixedMembershipResolver(memberships),
    )


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_settings_loads_supabase_values_and_auth_flag(tmp_path, monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", SUPABASE_URL)
    monkeypatch.setenv("SUPABASE_PUBLISHABLE_KEY", "test-publishable-key")
    monkeypatch.setenv("SUPABASE_DB_URL", "postgresql://server-only")
    monkeypatch.setenv("AUTH_REQUIRED", "true")

    settings = Settings.load(cwd=tmp_path)

    assert settings.supabase_url == SUPABASE_URL
    assert settings.supabase_publishable_key == "test-publishable-key"
    assert settings.supabase_db_url == "postgresql://server-only"
    assert settings.auth_required is True


def test_verifier_accepts_valid_token(token_tools):
    verifier, make_token = token_tools
    token = make_token()

    user = verifier.verify(token)

    assert user.user_id == USER_ID
    assert user.email == "operator@example.com"
    assert user.access_token == token
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


def test_membership_resolver_uses_user_token_and_rls(token_tools):
    verifier, make_token = token_tools
    token = make_token()
    user = verifier.verify(token)

    def respond(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == f"Bearer {token}"
        assert request.headers["apikey"] == "test-publishable-key"
        assert request.url.params["user_id"] == f"eq.{USER_ID}"
        return httpx.Response(
            200,
            json=[
                {
                    "organization_id": str(ORGANIZATION_ID),
                    "role": "operator",
                    "created_at": "2026-08-08T00:00:00Z",
                    "organizations": {
                        "id": str(ORGANIZATION_ID),
                        "name": "Reudan",
                        "slug": "reudan",
                    },
                }
            ],
        )

    resolver = SupabaseMembershipResolver(
        SUPABASE_URL,
        "test-publishable-key",
        http_client=httpx.Client(transport=httpx.MockTransport(respond)),
    )

    assert resolver.resolve(user) == (membership(),)


def test_public_endpoints_do_not_require_auth(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", SUPABASE_URL)
    monkeypatch.setenv("SUPABASE_PUBLISHABLE_KEY", "test-publishable-key")
    client = TestClient(app)

    assert client.get("/api/health").status_code == 200
    config_response = client.get("/api/public-config")
    assert config_response.status_code == 200
    assert config_response.json() == {
        "supabase_url": SUPABASE_URL,
        "supabase_publishable_key": "test-publishable-key",
        "auth_required": True,
    }
    assert "SUPABASE_DB_URL" not in config_response.text


@pytest.mark.parametrize(
    ("method", "path", "kwargs"),
    [
        ("get", "/api/me", {}),
        ("get", "/api/imports", {}),
        ("post", "/api/imports", {"files": {"file": ("rates.csv", b"x")}}),
        ("get", "/api/imports/missing", {}),
        ("post", "/api/imports/missing/approve", {"json": {"approved_by": "test"}}),
        ("post", "/api/imports/missing/reject", {"json": {"reason": "test"}}),
        ("delete", "/api/imports/missing", {}),
        ("get", "/api/search", {}),
        ("get", "/api/rate-desk/meta", {}),
        ("get", "/api/rate-desk/search", {}),
        ("get", "/api/rate-desk/offers/missing", {}),
        ("get", "/api/rate-desk", {}),
    ],
)
def test_every_sensitive_api_requires_a_token(method, path, kwargs):
    response = getattr(TestClient(app), method)(path, **kwargs)

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


@pytest.mark.parametrize("authorization", ["Basic abc", "Bearer", "Bearer abc extra"])
def test_api_rejects_malformed_authorization_header(authorization):
    response = TestClient(app).get(
        "/api/rate-desk",
        headers={"Authorization": authorization},
    )

    assert response.status_code == 401


def test_api_rejects_invalid_and_expired_jwts(token_tools, monkeypatch):
    verifier, make_token = token_tools
    use_auth(monkeypatch, verifier, (membership(),))
    client = TestClient(app)

    invalid_response = client.get(
        "/api/rate-desk",
        headers={"Authorization": "Bearer not-a-jwt"},
    )
    expired_response = client.get(
        "/api/rate-desk",
        headers=bearer(
            make_token(exp=datetime.now(timezone.utc) - timedelta(minutes=1))
        ),
    )

    assert invalid_response.status_code == 401
    assert expired_response.status_code == 401


def test_valid_user_without_membership_is_forbidden(token_tools, monkeypatch):
    verifier, make_token = token_tools
    use_auth(monkeypatch, verifier, ())

    response = TestClient(app).get(
        "/api/rate-desk",
        headers=bearer(make_token()),
    )

    assert response.status_code == 403


def test_api_me_returns_membership_context(token_tools, monkeypatch):
    verifier, make_token = token_tools
    use_auth(monkeypatch, verifier, (membership(),))

    response = TestClient(app).get("/api/me", headers=bearer(make_token()))

    assert response.status_code == 200
    assert response.json() == {
        "user_id": str(USER_ID),
        "email": "operator@example.com",
        "organizations": [
            {
                "id": str(ORGANIZATION_ID),
                "name": "Reudan",
                "slug": "reudan",
                "role": "operator",
            }
        ],
    }


@pytest.mark.parametrize("role", ["viewer", "operator", "admin"])
def test_all_membership_roles_can_read(role, token_tools, monkeypatch, tmp_path):
    monkeypatch.setenv("RATE_INGEST_ROOT", str(tmp_path))
    verifier, make_token = token_tools
    use_auth(monkeypatch, verifier, (membership(role),))
    client = TestClient(app)

    assert client.get("/api/imports", headers=bearer(make_token())).status_code == 200
    assert client.get("/api/search", headers=bearer(make_token())).status_code == 200
    assert client.get("/api/rate-desk/meta", headers=bearer(make_token())).status_code == 200
    assert client.get("/api/rate-desk/search", headers=bearer(make_token())).status_code == 200
    assert client.get("/api/rate-desk", headers=bearer(make_token())).status_code == 200


def test_viewer_cannot_mutate(token_tools, monkeypatch):
    verifier, make_token = token_tools
    use_auth(monkeypatch, verifier, (membership("viewer"),))
    headers = bearer(make_token())
    client = TestClient(app)

    assert client.post(
        "/api/imports",
        headers=headers,
        files={"file": ("rates.csv", b"x")},
    ).status_code == 403
    assert client.post(
        "/api/imports/missing/approve",
        headers=headers,
        json={"approved_by": "test"},
    ).status_code == 403
    assert client.post(
        "/api/imports/missing/reject",
        headers=headers,
        json={"reason": "test"},
    ).status_code == 403
    assert client.delete("/api/imports/missing", headers=headers).status_code == 403


@pytest.mark.parametrize("role", ["operator", "admin"])
def test_operator_and_admin_pass_mutation_gate(role, token_tools, monkeypatch):
    verifier, make_token = token_tools
    use_auth(monkeypatch, verifier, (membership(role),))
    context = RequestContext(
        user=verifier.verify(make_token()),
        memberships=(membership(role),),
    )

    assert require_operator(context) is context


def test_same_origin_app_has_no_wildcard_cors():
    response = TestClient(app).get(
        "/api/health",
        headers={"Origin": "https://untrusted.example"},
    )

    assert response.status_code == 200
    assert "access-control-allow-origin" not in response.headers


def test_frontend_has_invite_only_auth_gate_and_shared_api_helper():
    login_html = Path("UI/login.html").read_text(encoding="utf-8")
    import_html = Path("UI/import.html").read_text(encoding="utf-8")
    quote_html = Path("UI/index.html").read_text(encoding="utf-8")
    styles_css = Path("UI/styles.css").read_text(encoding="utf-8")
    auth_js = Path("UI/auth.js").read_text(encoding="utf-8")
    app_js = Path("UI/app.js").read_text(encoding="utf-8")
    rate_desk_js = Path("UI/rate-desk.js").read_text(encoding="utf-8")

    assert "@supabase/supabase-js@2.112.2" in login_html
    assert "Create Account" not in login_html
    assert "/ui/auth.js" in import_html
    assert "/ui/auth.js" in quote_html
    assert "signInWithPassword" in auth_js
    assert "getSession" in auth_js
    assert "signOut" in auth_js
    assert 'headers.set("Authorization", `Bearer ${session.access_token}`)' in auth_js
    assert "fetch(" not in app_js
    assert "fetch(" not in rate_desk_js
    assert "RATE_DESK_AUTH.apiFetch" in app_js
    assert "RATE_DESK_AUTH.apiFetch" in rate_desk_js
    assert 'carrier_label: "MSC · Door-to-quay"' in app_js
    assert 'carrier_label: "Hapag-Lloyd · Door-to-quay"' in app_js
    assert 'value="sea">SEA rates' in import_html
    assert 'value="india">India rates' in import_html
    assert "hapagRateTypeSelect" in app_js
    assert "maerskRateTypeSelect" in app_js
    assert "Maersk · India rates" in app_js
    assert "Maersk · SEA rates" in app_js
    assert 'carrier_key: sourceKey' in app_js
    assert 'carrier_label: "Hapag-Lloyd · India Door-to-quay"' in app_js
    assert 'carrier_label: "MSC · Quay-to-quay"' not in app_js
    assert 'carrier_label: "Hapag-Lloyd · Quay-to-quay"' not in app_js
    assert '"/api/rate-desk/meta"' in rate_desk_js
    assert "/api/rate-desk/search?" in rate_desk_js
    assert 'id="carrierSelect"' in quote_html
    assert "carrierSelect" in rate_desk_js
    assert 'params.set("carrier_name", carrier)' in rate_desk_js
    assert "/api/rate-desk/offers/${encodeURIComponent(offerId)}" in rate_desk_js
    assert "deskState.totalMatches" in rate_desk_js
    assert "deskState.pageSize" in rate_desk_js
    assert '"40hdry"' in rate_desk_js
    assert ": [...portRates, ...doorRates]" in rate_desk_js
    assert rate_desk_js.count("countsTowardTotal: line.counts_toward_total !== false") >= 2
    assert 'normalized(rate.offer_reference) === "peute"' in rate_desk_js
    assert "customerSpecific: true" in rate_desk_js
    assert ".service-tags .customer-rate-tag" in styles_css
    assert "inlandIncluded: true" in rate_desk_js
    assert "Inland haulage included in quoted door-to-quay rate" in rate_desk_js
    assert 'class="included-inland"' in rate_desk_js
    assert ".included-inland" in styles_css
    assert "Object.keys(tables || {})" in app_js


def test_invitation_and_recovery_password_page_enforces_safe_acceptance_flow():
    password_html = Path("UI/set-password.html").read_text(encoding="utf-8")
    password_js = Path("UI/set-password.js").read_text(encoding="utf-8")
    auth_js = Path("UI/auth.js").read_text(encoding="utf-8")

    assert "@supabase/supabase-js@2.112.2" in password_html
    assert 'minlength="8"' in password_html
    assert "signUp" not in password_html
    assert "signUp" not in password_js
    assert "hasPasswordSetupMarker" not in password_js
    assert "getSession()" in password_js
    assert "hasAuthLinkError()" in password_js
    assert "invalid or has expired" in password_js
    assert "password recovery link" in password_js
    assert "password !== confirmInput.value" in password_js
    assert "updateUser({ password })" in password_js
    assert 'error?.code === "same_password"' in password_js
    assert "different from your current password" in password_js
    assert 'RATE_DESK_AUTH.apiFetch("/api/me")' in password_js
    assert "has no organization access" in password_js
    assert 'signOut({ scope: "local" })' in password_js
    assert 'SET_PASSWORD_PATH = "/ui/set-password.html"' in auth_js
    assert "service_role" not in password_html
    assert "service_role" not in password_js
