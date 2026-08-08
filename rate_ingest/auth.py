from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Annotated, Any
from uuid import UUID

import httpx
import jwt
from fastapi import Depends, Header, HTTPException, status
from jwt import PyJWKClient
from jwt.exceptions import PyJWKClientError, PyJWTError

from rate_ingest.config import Settings


ALLOWED_ASYMMETRIC_ALGORITHMS = frozenset({"ES256", "RS256", "EdDSA"})
AUTHENTICATED_AUDIENCE = "authenticated"
ALLOWED_ORGANIZATION_ROLES = frozenset({"viewer", "operator", "admin"})
MUTATING_ORGANIZATION_ROLES = frozenset({"operator", "admin"})


class AuthenticationError(ValueError):
    """The bearer token is not a valid Supabase user token."""


class AuthConfigurationError(RuntimeError):
    """The server has no usable Supabase authentication configuration."""


class MembershipLookupError(RuntimeError):
    """The organization membership service could not complete its request."""


@dataclass(frozen=True)
class AuthenticatedUser:
    user_id: UUID
    email: str | None
    access_token: str
    claims: dict[str, Any]


@dataclass(frozen=True)
class OrganizationMembership:
    organization_id: UUID
    organization_name: str
    organization_slug: str | None
    role: str

    def as_dict(self) -> dict[str, str | None]:
        return {
            "id": str(self.organization_id),
            "name": self.organization_name,
            "slug": self.organization_slug,
            "role": self.role,
        }


@dataclass(frozen=True)
class RequestContext:
    user: AuthenticatedUser
    memberships: tuple[OrganizationMembership, ...]

    @property
    def organization_id(self) -> UUID:
        return self.memberships[0].organization_id

    @property
    def organization_role(self) -> str:
        return self.memberships[0].role


class SupabaseTokenVerifier:
    """Verify asymmetric Supabase access tokens with the public JWKS."""

    def __init__(
        self,
        supabase_url: str,
        *,
        jwks_client: PyJWKClient | None = None,
    ) -> None:
        base_url = supabase_url.strip().rstrip("/")
        if not base_url.startswith("https://"):
            raise AuthConfigurationError("SUPABASE_URL must use HTTPS")
        self.issuer = f"{base_url}/auth/v1"
        self.jwks_url = f"{self.issuer}/.well-known/jwks.json"
        self._jwks_client = jwks_client or PyJWKClient(
            self.jwks_url,
            cache_jwk_set=True,
            lifespan=600,
            timeout=5,
        )

    def verify(self, token: str) -> AuthenticatedUser:
        try:
            header = jwt.get_unverified_header(token)
            algorithm = header.get("alg")
            if algorithm not in ALLOWED_ASYMMETRIC_ALGORITHMS:
                raise AuthenticationError("Unsupported JWT signing algorithm")

            signing_key = self._jwks_client.get_signing_key_from_jwt(token)
            claims = jwt.decode(
                token,
                signing_key.key,
                algorithms=[algorithm],
                audience=AUTHENTICATED_AUDIENCE,
                issuer=self.issuer,
                options={"require": ["exp", "iss", "aud", "sub"]},
            )
            if claims.get("role") != AUTHENTICATED_AUDIENCE:
                raise AuthenticationError("JWT role is not authenticated")

            user_id = UUID(str(claims["sub"]))
            email_claim = claims.get("email")
            email = email_claim if isinstance(email_claim, str) else None
            return AuthenticatedUser(
                user_id=user_id,
                email=email,
                access_token=token,
                claims=dict(claims),
            )
        except AuthenticationError:
            raise
        except (KeyError, TypeError, ValueError, PyJWTError, PyJWKClientError) as exc:
            raise AuthenticationError("Invalid or expired bearer token") from exc


@lru_cache(maxsize=4)
def _cached_verifier(supabase_url: str) -> SupabaseTokenVerifier:
    return SupabaseTokenVerifier(supabase_url)


def get_token_verifier() -> SupabaseTokenVerifier:
    supabase_url = Settings.load().supabase_url
    if not supabase_url:
        raise AuthConfigurationError("SUPABASE_URL is not configured")
    return _cached_verifier(supabase_url)


class SupabaseMembershipResolver:
    """Read the signed-in user's memberships through Supabase RLS."""

    def __init__(
        self,
        supabase_url: str,
        publishable_key: str,
        *,
        http_client: httpx.Client | None = None,
    ) -> None:
        base_url = supabase_url.strip().rstrip("/")
        if not base_url.startswith("https://"):
            raise AuthConfigurationError("SUPABASE_URL must use HTTPS")
        if not publishable_key.strip():
            raise AuthConfigurationError("SUPABASE_PUBLISHABLE_KEY is not configured")
        self.memberships_url = f"{base_url}/rest/v1/organization_members"
        self._publishable_key = publishable_key.strip()
        self._http_client = http_client or httpx.Client(timeout=5.0)

    def resolve(
        self,
        user: AuthenticatedUser,
    ) -> tuple[OrganizationMembership, ...]:
        try:
            response = self._http_client.get(
                self.memberships_url,
                params={
                    "select": "organization_id,role,created_at,organizations(id,name,slug)",
                    "user_id": f"eq.{user.user_id}",
                    "order": "created_at.asc",
                    "limit": "20",
                },
                headers={
                    "apikey": self._publishable_key,
                    "Authorization": f"Bearer {user.access_token}",
                    "Accept": "application/json",
                },
            )
        except httpx.HTTPError as exc:
            raise MembershipLookupError("Supabase membership lookup failed") from exc

        if response.status_code == status.HTTP_401_UNAUTHORIZED:
            raise AuthenticationError("Supabase rejected the access token")
        if response.status_code != status.HTTP_200_OK:
            raise MembershipLookupError("Supabase membership lookup failed")

        try:
            rows = response.json()
        except ValueError as exc:
            raise MembershipLookupError("Supabase returned invalid membership data") from exc
        if not isinstance(rows, list):
            raise MembershipLookupError("Supabase returned invalid membership data")

        memberships: list[OrganizationMembership] = []
        for row in rows:
            if not isinstance(row, dict):
                raise MembershipLookupError("Supabase returned invalid membership data")
            organization = row.get("organizations")
            if not isinstance(organization, dict):
                raise MembershipLookupError("Membership has no organization record")
            role = row.get("role")
            if role not in ALLOWED_ORGANIZATION_ROLES:
                raise MembershipLookupError("Membership has an invalid role")
            try:
                organization_id = UUID(str(row["organization_id"]))
            except (KeyError, TypeError, ValueError) as exc:
                raise MembershipLookupError("Membership has an invalid organization ID") from exc
            name = organization.get("name")
            slug = organization.get("slug")
            if not isinstance(name, str) or not name.strip():
                raise MembershipLookupError("Membership has no organization name")
            memberships.append(
                OrganizationMembership(
                    organization_id=organization_id,
                    organization_name=name.strip(),
                    organization_slug=slug.strip() if isinstance(slug, str) and slug.strip() else None,
                    role=role,
                )
            )
        return tuple(memberships)


@lru_cache(maxsize=4)
def _cached_membership_resolver(
    supabase_url: str,
    publishable_key: str,
) -> SupabaseMembershipResolver:
    return SupabaseMembershipResolver(supabase_url, publishable_key)


def get_membership_resolver() -> SupabaseMembershipResolver:
    settings = Settings.load()
    if not settings.supabase_url or not settings.supabase_publishable_key:
        raise AuthConfigurationError("Supabase membership lookup is not configured")
    return _cached_membership_resolver(
        settings.supabase_url,
        settings.supabase_publishable_key,
    )


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def require_authenticated_user(
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
) -> AuthenticatedUser:
    if authorization is None:
        raise _unauthorized("Bearer token is required")

    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1]:
        raise _unauthorized("Authorization header must use Bearer <token>")

    try:
        return get_token_verifier().verify(parts[1])
    except AuthenticationError as exc:
        raise _unauthorized("Bearer token is invalid or expired") from exc
    except AuthConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication service is not configured",
        ) from exc


def require_organization_member(
    user: Annotated[AuthenticatedUser, Depends(require_authenticated_user)],
) -> RequestContext:
    try:
        memberships = get_membership_resolver().resolve(user)
    except AuthenticationError as exc:
        raise _unauthorized("Bearer token is invalid or expired") from exc
    except (AuthConfigurationError, MembershipLookupError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Organization membership service is unavailable",
        ) from exc
    if not memberships:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No active organization membership was found",
        )
    return RequestContext(user=user, memberships=memberships)


def require_operator(
    context: Annotated[RequestContext, Depends(require_organization_member)],
) -> RequestContext:
    if context.organization_role not in MUTATING_ORGANIZATION_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Operator or admin access is required",
        )
    return context
