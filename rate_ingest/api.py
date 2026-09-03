from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated
from uuid import uuid4

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from rate_ingest.auth import (
    RequestContext,
    require_operator,
    require_organization_member,
)
from rate_ingest.config import Settings
from rate_ingest.repositories import close_rate_repositories
from rate_ingest.services import (
    approve_import_by_id,
    delete_import_by_id,
    get_rate_desk_data,
    get_rate_desk_metadata,
    get_rate_offer_detail,
    get_import_detail,
    export_rate_desk_csv,
    import_source_file,
    list_imports,
    reject_import_by_id,
    search_approved_offers,
    search_rate_summaries,
)
from rate_ingest.source_storage import SourceStorageError


class ApproveRequest(BaseModel):
    approved_by: str
    carrier_name: str | None = None
    carrier_key: str | None = None
    carrier_label: str | None = None
    contract_tag: str | None = None


class RejectRequest(BaseModel):
    reason: str


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    try:
        yield
    finally:
        close_rate_repositories()


app = FastAPI(title="Freight Rate Ingest API", version="0.1.0", lifespan=lifespan)


def settings() -> Settings:
    loaded = Settings.load()
    loaded.ensure()
    return loaded


@app.get("/")
def root() -> RedirectResponse:
    return RedirectResponse(url="/ui/login.html")


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/public-config")
def public_config() -> dict[str, str | bool]:
    cfg = Settings.load()
    if not cfg.supabase_url or not cfg.supabase_publishable_key:
        raise HTTPException(
            status_code=503,
            detail="Supabase login is not configured",
        )
    return {
        "supabase_url": cfg.supabase_url,
        "supabase_publishable_key": cfg.supabase_publishable_key,
        "auth_required": True,
    }


@app.get("/api/me")
def api_me(
    context: Annotated[RequestContext, Depends(require_organization_member)],
) -> dict:
    return {
        "user_id": str(context.user.user_id),
        "email": context.user.email,
        "organizations": [membership.as_dict() for membership in context.memberships],
    }


@app.get("/api/imports")
def api_list_imports(
    context: Annotated[RequestContext, Depends(require_organization_member)],
    limit: int = 50,
) -> list[dict]:
    return list_imports(
        settings(), limit=limit, organization_id=context.organization_id
    )


@app.post("/api/imports")
async def api_import_source(
    context: Annotated[RequestContext, Depends(require_operator)],
    file: UploadFile = File(...),
    template: str | None = Form(default=None),
    uploaded_by: str | None = Form(default=None),
) -> dict:
    cfg = settings()
    uploads_dir = cfg.data_dir / "tmp_uploads"
    uploads_dir.mkdir(parents=True, exist_ok=True)
    original_name = Path(file.filename or "upload.bin").name
    suffix = Path(original_name).suffix
    temp_path = uploads_dir / f"{uuid4().hex}{suffix}"
    temp_path.write_bytes(await file.read())
    try:
        return import_source_file(
            cfg,
            temp_path,
            template=template,
            uploaded_by=uploaded_by,
            source_file_name=original_name,
            source_storage_access_token=context.user.access_token,
            organization_id=context.organization_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SourceStorageError as exc:
        raise HTTPException(
            status_code=503,
            detail="Private source storage is unavailable",
        ) from exc
    finally:
        temp_path.unlink(missing_ok=True)


@app.get("/api/imports/{import_id}")
def api_get_import(
    import_id: str,
    context: Annotated[RequestContext, Depends(require_organization_member)],
) -> dict:
    try:
        return get_import_detail(
            settings(), import_id, organization_id=context.organization_id
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/imports/{import_id}/approve")
def api_approve_import(
    import_id: str,
    payload: ApproveRequest,
    context: Annotated[RequestContext, Depends(require_operator)],
) -> dict:
    try:
        return approve_import_by_id(
            settings(),
            import_id,
            payload.approved_by,
            carrier_name=payload.carrier_name,
            carrier_key=payload.carrier_key,
            carrier_label=payload.carrier_label,
            contract_tag=payload.contract_tag,
            organization_id=context.organization_id,
            approved_by_user_id=str(context.user.user_id),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/imports/{import_id}/reject")
def api_reject_import(
    import_id: str,
    payload: RejectRequest,
    context: Annotated[RequestContext, Depends(require_operator)],
) -> dict:
    try:
        return reject_import_by_id(
            settings(),
            import_id,
            payload.reason,
            organization_id=context.organization_id,
            rejected_by_user_id=str(context.user.user_id),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.delete("/api/imports/{import_id}")
def api_delete_import(
    import_id: str,
    context: Annotated[RequestContext, Depends(require_operator)],
) -> dict:
    try:
        return delete_import_by_id(
            settings(),
            import_id,
            organization_id=context.organization_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/search")
def api_search(
    context: Annotated[RequestContext, Depends(require_organization_member)],
    provider_name: str | None = None,
    carrier_name: list[str] | None = Query(default=None),
    collection: list[str] | None = Query(default=None),
    pol: list[str] | None = Query(default=None),
    pod: list[str] | None = Query(default=None),
    equipment_type: str | None = None,
    material: str | None = None,
    valid_on: str | None = None,
    limit: int = 200,
) -> list[dict]:
    return search_approved_offers(
        settings(),
        provider_name=provider_name,
        carrier_name=carrier_name,
        collection=collection,
        pol=pol,
        pod=pod,
        equipment_type=equipment_type,
        material=material,
        valid_on=valid_on,
        limit=limit,
        organization_id=context.organization_id,
    )


@app.get("/api/rate-desk/meta")
def api_rate_desk_metadata(
    context: Annotated[RequestContext, Depends(require_organization_member)],
) -> dict:
    return get_rate_desk_metadata(
        settings(),
        organization_id=context.organization_id,
    )


@app.get("/api/rate-desk/search")
def api_rate_desk_search(
    context: Annotated[RequestContext, Depends(require_organization_member)],
    provider_name: str | None = None,
    carrier_name: list[str] | None = Query(default=None),
    collection: list[str] | None = Query(default=None),
    pol: list[str] | None = Query(default=None),
    pod: list[str] | None = Query(default=None),
    equipment_type: str | None = None,
    material: str | None = None,
    valid_on: str | None = None,
    include_expired: bool = True,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    return search_rate_summaries(
        settings(),
        provider_name=provider_name,
        carrier_name=carrier_name,
        collection=collection,
        pol=pol,
        pod=pod,
        equipment_type=equipment_type,
        material=material,
        valid_on=valid_on,
        include_expired=include_expired,
        limit=min(max(limit, 1), 50),
        offset=max(offset, 0),
        organization_id=context.organization_id,
    )


@app.get("/api/rate-desk/offers/{offer_id}")
def api_rate_offer_detail(
    offer_id: str,
    context: Annotated[RequestContext, Depends(require_organization_member)],
) -> dict:
    detail = get_rate_offer_detail(
        settings(),
        offer_id,
        organization_id=context.organization_id,
    )
    if detail is None:
        raise HTTPException(status_code=404, detail="Approved rate offer not found")
    return detail


@app.get("/api/rate-desk/export")
def api_rate_desk_export(
    context: Annotated[RequestContext, Depends(require_organization_member)],
    provider_name: str | None = None,
    carrier_name: list[str] | None = Query(default=None),
    collection: list[str] | None = Query(default=None),
    pol: list[str] | None = Query(default=None),
    pod: list[str] | None = Query(default=None),
    equipment_type: str | None = None,
    material: str | None = None,
    include_expired: bool = True,
    containers: int = 1,
    margin_usd: float = 0.0,
) -> Response:
    try:
        csv_body = export_rate_desk_csv(
            settings(),
            provider_name=provider_name,
            carrier_name=carrier_name,
            collection=collection,
            pol=pol,
            pod=pod,
            equipment_type=equipment_type,
            material=material,
            include_expired=include_expired,
            containers=containers,
            margin_usd=margin_usd,
            organization_id=context.organization_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return Response(
        content=csv_body,
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="rate-desk-export.csv"'},
    )


@app.get("/api/rate-desk")
def api_rate_desk(
    context: Annotated[RequestContext, Depends(require_organization_member)],
    limit: int = 2000,
) -> dict:
    return get_rate_desk_data(
        settings(),
        limit=min(max(limit, 1), 5000),
        organization_id=context.organization_id,
    )


ui_dir = Path(__file__).resolve().parents[1] / "UI"
if ui_dir.exists():
    app.mount("/ui", StaticFiles(directory=ui_dir, html=True), name="ui")
