from __future__ import annotations

import mimetypes
from pathlib import Path, PurePosixPath
from urllib.parse import quote
from uuid import UUID

import httpx

from rate_ingest.models import SourceDocument
from rate_ingest.utils import safe_file_name


class SourceStorageError(RuntimeError):
    """The private source object could not be stored or retrieved."""


class SupabaseSourceStorage:
    """Small authenticated client for one private Supabase Storage bucket."""

    def __init__(
        self,
        supabase_url: str,
        publishable_key: str,
        bucket: str,
        *,
        http_client: httpx.Client | None = None,
    ) -> None:
        base_url = supabase_url.strip().rstrip("/")
        if not base_url.startswith("https://"):
            raise SourceStorageError("SUPABASE_URL must use HTTPS")
        if not publishable_key.strip():
            raise SourceStorageError("SUPABASE_PUBLISHABLE_KEY is not configured")
        if not bucket.strip() or "/" in bucket:
            raise SourceStorageError("SUPABASE_STORAGE_BUCKET is invalid")
        self._base_url = f"{base_url}/storage/v1"
        self._publishable_key = publishable_key.strip()
        self.bucket = bucket.strip()
        self._http_client = http_client or httpx.Client(timeout=60.0)
        self._owns_http_client = http_client is None

    def close(self) -> None:
        if self._owns_http_client:
            self._http_client.close()

    def upload(
        self,
        source_path: Path,
        object_path: str,
        *,
        access_token: str,
    ) -> None:
        normalized_path = _validated_object_path(object_path)
        content_type = mimetypes.guess_type(source_path.name)[0]
        with source_path.open("rb") as source_file:
            try:
                response = self._http_client.post(
                    self._object_url(normalized_path),
                    headers={
                        **self._auth_headers(access_token),
                        "Content-Type": content_type or "application/octet-stream",
                        "Cache-Control": "31536000, immutable",
                    },
                    content=source_file,
                )
            except httpx.HTTPError as exc:
                raise SourceStorageError("Supabase source upload failed") from exc
        if response.status_code in {400, 409} and self._object_exists(
            normalized_path,
            access_token=access_token,
        ):
            return
        if not response.is_success:
            raise SourceStorageError(
                f"Supabase source upload failed with status {response.status_code}"
            )

    def download(
        self,
        object_path: str,
        *,
        access_token: str,
    ) -> bytes:
        normalized_path = _validated_object_path(object_path)
        try:
            response = self._http_client.get(
                self._authenticated_object_url(normalized_path),
                headers=self._auth_headers(access_token),
            )
        except httpx.HTTPError as exc:
            raise SourceStorageError("Supabase source download failed") from exc
        if not response.is_success:
            raise SourceStorageError(
                f"Supabase source download failed with status {response.status_code}"
            )
        return response.content

    def _auth_headers(self, access_token: str) -> dict[str, str]:
        token = access_token.strip()
        if not token:
            raise SourceStorageError("A signed-in user token is required for source storage")
        return {
            "apikey": self._publishable_key,
            "Authorization": f"Bearer {token}",
        }

    def _object_url(self, object_path: str) -> str:
        return (
            f"{self._base_url}/object/{quote(self.bucket, safe='')}/"
            f"{quote(object_path, safe='/')}"
        )

    def _authenticated_object_url(self, object_path: str) -> str:
        return (
            f"{self._base_url}/object/authenticated/{quote(self.bucket, safe='')}/"
            f"{quote(object_path, safe='/')}"
        )

    def _object_exists(self, object_path: str, *, access_token: str) -> bool:
        try:
            response = self._http_client.head(
                f"{self._base_url}/object/info/{quote(self.bucket, safe='')}/"
                f"{quote(object_path, safe='/')}",
                headers=self._auth_headers(access_token),
            )
        except httpx.HTTPError:
            return False
        return response.is_success


def build_source_object_path(
    organization_id: UUID,
    source: SourceDocument,
) -> str:
    return (
        f"{organization_id}/{source.id}/"
        f"{safe_file_name(Path(source.file_name).name)}"
    )


def is_source_object_path(value: str, organization_id: UUID) -> bool:
    try:
        parts = _validated_object_path(value).split("/")
    except SourceStorageError:
        return False
    return len(parts) >= 3 and parts[0] == str(organization_id)


def _validated_object_path(value: str) -> str:
    normalized = value.strip().lstrip("/")
    path = PurePosixPath(normalized)
    if not normalized or any(part in {"", ".", ".."} for part in path.parts):
        raise SourceStorageError("Source object path is invalid")
    return path.as_posix()
