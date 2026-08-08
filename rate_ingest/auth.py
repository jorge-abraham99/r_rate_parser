from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Annotated, Any
from uuid import UUID

import jwt
from fastapi import Header, HTTPException, status
from jwt import PyJWKClient
from jwt.exceptions import PyJWKClientError, PyJWTError

from rate_ingest.config import Settings


ALLOWED_ASYMMETRIC_ALGORITHMS = frozenset({"ES256", "RS256", "EdDSA"})
AUTHENTICATED_AUDIENCE = "authenticated"


class AuthenticationError(ValueError):
    """The bearer token is not a valid Supabase user token."""


class AuthConfigurationError(RuntimeError):
    """The server has no usable Supabase authentication configuration."""


@dataclass(frozen=True)
class AuthenticatedUser:
    user_id: UUID
    email: str | None
    claims: dict[str, Any]


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
