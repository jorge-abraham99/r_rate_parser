from __future__ import annotations

import os
from pathlib import Path
import sys
from uuid import UUID, uuid4

import httpx
import psycopg
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rate_ingest.config import Settings
from rate_ingest.repositories.postgres_repository import secure_connection_string
from rate_ingest.source_storage import SourceStorageError, SupabaseSourceStorage


RUN_INTEGRATION = (
    os.getenv("RUN_SUPABASE_STORAGE_INTEGRATION_TESTS", "").lower() == "true"
)


@pytest.mark.skipif(
    not RUN_INTEGRATION,
    reason="Set RUN_SUPABASE_STORAGE_INTEGRATION_TESTS=true to run",
)
def test_private_source_bucket_enforces_organization_roles(
    tmp_path: Path,
) -> None:
    settings = Settings.load()
    required = {
        "SUPABASE_URL": settings.supabase_url,
        "SUPABASE_PUBLISHABLE_KEY": settings.supabase_publishable_key,
        "SUPABASE_DB_URL": settings.supabase_db_url,
        "SUPABASE_ACCESS_TOKEN": os.getenv("SUPABASE_ACCESS_TOKEN"),
        "SUPABASE_PROJECT_REF": os.getenv("SUPABASE_PROJECT_REF"),
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        pytest.skip("Missing guarded integration settings: " + ", ".join(missing))

    supabase_url = str(settings.supabase_url).rstrip("/")
    publishable_key = str(settings.supabase_publishable_key)
    management_token = str(required["SUPABASE_ACCESS_TOKEN"])
    project_ref = str(required["SUPABASE_PROJECT_REF"])
    database_url = secure_connection_string(str(settings.supabase_db_url))
    user_ids: list[UUID] = []
    organization_ids: list[UUID] = []
    object_paths: list[str] = []

    api_keys_response = httpx.get(
        f"https://api.supabase.com/v1/projects/{project_ref}/api-keys",
        headers={"Authorization": f"Bearer {management_token}"},
        timeout=20,
    )
    api_keys_response.raise_for_status()
    service_role_key = next(
        item["api_key"]
        for item in api_keys_response.json()
        if item.get("name") == "service_role"
    )
    service_headers = {
        "apikey": service_role_key,
        "Authorization": f"Bearer {service_role_key}",
    }

    def create_user(label: str) -> tuple[UUID, str]:
        password = f"Stage8-{uuid4().hex}!"
        response = httpx.post(
            f"{supabase_url}/auth/v1/admin/users",
            headers=service_headers,
            json={
                "email": f"stage8-{label}-{uuid4().hex}@example.invalid",
                "password": password,
                "email_confirm": True,
            },
            timeout=20,
        )
        response.raise_for_status()
        user_id = UUID(response.json()["id"])
        user_ids.append(user_id)
        return user_id, password

    def sign_in(email_user_id: UUID, password: str) -> str:
        response = httpx.get(
            f"{supabase_url}/auth/v1/admin/users/{email_user_id}",
            headers=service_headers,
            timeout=20,
        )
        response.raise_for_status()
        email = response.json()["email"]
        login = httpx.post(
            f"{supabase_url}/auth/v1/token",
            params={"grant_type": "password"},
            headers={"apikey": publishable_key},
            json={"email": email, "password": password},
            timeout=20,
        )
        login.raise_for_status()
        return login.json()["access_token"]

    try:
        operator_id, operator_password = create_user("operator")
        outsider_id, outsider_password = create_user("outsider")
        operator_token = sign_in(operator_id, operator_password)
        outsider_token = sign_in(outsider_id, outsider_password)
        organization_a = uuid4()
        organization_b = uuid4()
        organization_ids.extend((organization_a, organization_b))
        suffix = uuid4().hex[:12]
        with psycopg.connect(
            database_url,
            autocommit=True,
            prepare_threshold=None,
        ) as connection:
            with connection.cursor() as cursor:
                cursor.executemany(
                    """
                    insert into public.organizations (id, name, slug)
                    values (%s, %s, %s)
                    """,
                    (
                        (
                            organization_a,
                            "Stage 8 Storage A",
                            f"stage8-storage-a-{suffix}",
                        ),
                        (
                            organization_b,
                            "Stage 8 Storage B",
                            f"stage8-storage-b-{suffix}",
                        ),
                    ),
                )
                cursor.executemany(
                    """
                    insert into public.organization_members
                        (organization_id, user_id, role)
                    values (%s, %s, %s)
                    """,
                    (
                        (organization_a, operator_id, "operator"),
                        (organization_b, outsider_id, "operator"),
                    ),
                )

        source_path = tmp_path / "stage8-source.txt"
        source_path.write_bytes(b"stage-8-private-source")
        object_path = f"{organization_a}/src_stage8/source.txt"
        viewer_path = f"{organization_a}/src_stage8_viewer/source.txt"
        object_paths.extend((object_path, viewer_path))
        storage = SupabaseSourceStorage(
            supabase_url,
            publishable_key,
            settings.supabase_storage_bucket,
        )
        try:
            storage.upload(
                source_path,
                object_path,
                access_token=operator_token,
            )
            storage.upload(
                source_path,
                object_path,
                access_token=operator_token,
            )
            assert (
                storage.download(object_path, access_token=operator_token)
                == b"stage-8-private-source"
            )
            with pytest.raises(SourceStorageError, match="status (400|403|404)"):
                storage.download(object_path, access_token=outsider_token)

            with psycopg.connect(
                database_url,
                autocommit=True,
                prepare_threshold=None,
            ) as connection:
                connection.execute(
                    """
                    insert into public.organization_members
                        (organization_id, user_id, role)
                    values (%s, %s, 'viewer')
                    """,
                    (organization_a, outsider_id),
                )
            assert (
                storage.download(object_path, access_token=outsider_token)
                == b"stage-8-private-source"
            )
            with pytest.raises(SourceStorageError, match="status (400|403)"):
                storage.upload(
                    source_path,
                    viewer_path,
                    access_token=outsider_token,
                )

            public_response = httpx.get(
                f"{supabase_url}/storage/v1/object/public/"
                f"{settings.supabase_storage_bucket}/{object_path}",
                headers={"apikey": publishable_key},
                timeout=20,
            )
            assert public_response.status_code in {400, 403, 404}
        finally:
            storage.close()
    finally:
        if object_paths:
            httpx.request(
                "DELETE",
                f"{supabase_url}/storage/v1/object/"
                f"{settings.supabase_storage_bucket}",
                headers=service_headers,
                json={"prefixes": object_paths},
                timeout=20,
            )
        if organization_ids:
            with psycopg.connect(
                database_url,
                autocommit=True,
                prepare_threshold=None,
            ) as connection:
                connection.execute(
                    "delete from public.organizations where id = any(%s)",
                    (organization_ids,),
                )
        for user_id in user_ids:
            httpx.delete(
                f"{supabase_url}/auth/v1/admin/users/{user_id}",
                headers=service_headers,
                timeout=20,
            )
