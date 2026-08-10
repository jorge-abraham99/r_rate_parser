from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import sys
from unittest.mock import MagicMock, Mock
from uuid import UUID

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rate_ingest.config import Settings
from rate_ingest.models import SourceDocument
from rate_ingest.repositories import RateRepository
from rate_ingest.repositories.postgres_repository import PostgresRateRepository
from rate_ingest.services import import_source_file
from rate_ingest.source_storage import (
    SourceStorageError,
    SupabaseSourceStorage,
    build_source_object_path,
)


ORGANIZATION_ID = UUID("123e4567-e89b-12d3-a456-426614174001")


def test_supabase_source_storage_uses_user_token_and_private_object_routes(
    tmp_path: Path,
) -> None:
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "POST":
            return httpx.Response(200, json={"Key": "stored"})
        return httpx.Response(200, content=b"original-rate-file")

    storage = SupabaseSourceStorage(
        "https://project.supabase.co",
        "sb_publishable_test",
        "rate-sources",
        http_client=httpx.Client(transport=httpx.MockTransport(respond)),
    )
    source_path = tmp_path / "rates.xlsx"
    source_path.write_bytes(b"original-rate-file")
    object_path = f"{ORGANIZATION_ID}/src_test/Client_Rates.xlsx"

    storage.upload(source_path, object_path, access_token="user-access-token")
    downloaded = storage.download(object_path, access_token="user-access-token")

    assert downloaded == b"original-rate-file"
    assert requests[0].url.path.endswith(f"/object/rate-sources/{object_path}")
    assert requests[1].url.path.endswith(
        f"/object/authenticated/rate-sources/{object_path}"
    )
    assert requests[0].headers["authorization"] == "Bearer user-access-token"
    assert requests[0].headers["apikey"] == "sb_publishable_test"
    assert requests[0].headers["cache-control"] == "31536000, immutable"
    assert requests[0].content == b"original-rate-file"


def test_source_object_path_is_organization_scoped_and_sanitized() -> None:
    source = SourceDocument(
        id="src_test",
        source_type="xlsx",
        file_name="../Client + Rates.xlsx",
        source_path="/tmp/source.xlsx",
        checksum="a" * 64,
    )

    object_path = build_source_object_path(ORGANIZATION_ID, source)

    assert object_path == f"{ORGANIZATION_ID}/src_test/Client _ Rates.xlsx"
    assert ".." not in object_path


def test_source_storage_rejects_invalid_paths_and_missing_tokens(
    tmp_path: Path,
) -> None:
    storage = SupabaseSourceStorage(
        "https://project.supabase.co",
        "sb_publishable_test",
        "rate-sources",
        http_client=httpx.Client(
            transport=httpx.MockTransport(
                lambda _request: httpx.Response(200)
            )
        ),
    )
    source_path = tmp_path / "rates.xlsx"
    source_path.write_bytes(b"rates")

    with pytest.raises(SourceStorageError, match="path is invalid"):
        storage.upload(source_path, "../rates.xlsx", access_token="token")
    with pytest.raises(SourceStorageError, match="signed-in user token"):
        storage.upload(source_path, "org/source/rates.xlsx", access_token="")


def test_source_upload_retry_accepts_an_existing_readable_object(
    tmp_path: Path,
) -> None:
    methods: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        methods.append(request.method)
        return httpx.Response(400 if request.method == "POST" else 200)

    storage = SupabaseSourceStorage(
        "https://project.supabase.co",
        "sb_publishable_test",
        "rate-sources",
        http_client=httpx.Client(transport=httpx.MockTransport(respond)),
    )
    source_path = tmp_path / "rates.xlsx"
    source_path.write_bytes(b"rates")

    storage.upload(
        source_path,
        "organization/source/rates.xlsx",
        access_token="user-access-token",
    )

    assert methods == ["POST", "HEAD"]


def test_postgres_repository_uploads_once_then_persists_object_path(
    tmp_path: Path,
) -> None:
    settings = replace(
        Settings.load(cwd=tmp_path),
        rate_storage_backend="postgres",
        source_storage_backend="supabase",
        supabase_url="https://project.supabase.co",
        supabase_publishable_key="sb_publishable_test",
    )
    pool = MagicMock()
    connection = pool.connection.return_value.__enter__.return_value
    connection.execute.return_value.fetchone.return_value = {"storage_path": None}
    storage = Mock(spec=SupabaseSourceStorage)
    repository = PostgresRateRepository(
        settings,
        pool=pool,
        source_storage=storage,
    )
    source_path = tmp_path / "Client rates.xlsx"
    source_path.write_bytes(b"rates")
    source = SourceDocument(
        id="src_test",
        source_type="xlsx",
        file_name=source_path.name,
        source_path=str(source_path),
        checksum="a" * 64,
    )

    stored = repository.persist_source_file(
        source,
        source_path,
        organization_id=ORGANIZATION_ID,
        access_token="user-access-token",
    )

    expected_path = f"{ORGANIZATION_ID}/src_test/Client rates.xlsx"
    storage.upload.assert_called_once_with(
        source_path,
        expected_path,
        access_token="user-access-token",
    )
    assert stored.source_path == expected_path
    update_call = connection.execute.call_args_list[1]
    assert "update public.source_documents" in update_call.args[0]
    assert update_call.args[1][0] == expected_path


def test_parser_uses_local_file_before_source_moves_to_object_storage(
    tmp_path: Path,
) -> None:
    settings = Settings.load(cwd=tmp_path)
    settings.ensure()
    source_path = Path("rate_sheet_files/HAPAG - FAR EAST RATES.xlsx")
    source = SourceDocument(
        id="src_storage_parse",
        source_type="xlsx",
        file_name=source_path.name,
        source_path="remote/path/that/is/not/a/local/file.xlsx",
        checksum="a" * 64,
    )
    stored_source = source.model_copy(
        update={
            "source_path": f"{ORGANIZATION_ID}/{source.id}/{source.file_name}"
        }
    )
    repository = Mock(spec=RateRepository)
    repository.register_source_document.return_value = source
    repository.persist_source_file.return_value = stored_source

    result = import_source_file(
        settings,
        source_path,
        repository=repository,
        organization_id=ORGANIZATION_ID,
        source_storage_access_token="user-access-token",
    )

    assert result["parser_family"] == "hapag_door_matrix"
    assert result["counts"]["rate_offers"] > 0
    assert result["source"]["source_path"] == stored_source.source_path
    repository.persist_source_file.assert_called_once_with(
        source,
        source_path,
        organization_id=ORGANIZATION_ID,
        access_token="user-access-token",
    )
    repository.save_import_bundle.assert_called_once()


def test_rate_source_migration_is_private_and_organization_scoped() -> None:
    migration = Path(
        "supabase/migrations/20260810223319_add_private_rate_source_storage.sql"
    ).read_text(encoding="utf-8")
    local_config = Path("supabase/config.toml").read_text(encoding="utf-8")

    assert "[storage.buckets.rate-sources]" in local_config
    assert "public = false" in local_config
    assert migration.count("on storage.objects") == 2
    assert "for select" in migration
    assert "for insert" in migration
    assert "to authenticated" in migration
    assert "storage.foldername(name)" in migration
    assert "public.organization_members" in migration
    assert "om.role in ('admin', 'operator')" in migration
    assert "for update" not in migration
    assert "for delete" not in migration
