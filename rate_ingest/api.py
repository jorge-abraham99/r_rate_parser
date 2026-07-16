from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from rate_ingest.config import Settings
from rate_ingest.services import (
    approve_import_by_id,
    delete_import_by_id,
    get_rate_desk_data,
    get_import_detail,
    import_source_file,
    list_imports,
    reject_import_by_id,
    search_approved_offers,
)


class ApproveRequest(BaseModel):
    approved_by: str
    carrier_name: str | None = None
    carrier_key: str | None = None
    carrier_label: str | None = None
    contract_tag: str | None = None


class RejectRequest(BaseModel):
    reason: str


app = FastAPI(title="Freight Rate Ingest API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def settings() -> Settings:
    loaded = Settings.load()
    loaded.ensure()
    return loaded


@app.get("/")
def root() -> RedirectResponse:
    return RedirectResponse(url="/ui/")


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/imports")
def api_list_imports(limit: int = 50) -> list[dict]:
    return list_imports(settings(), limit=limit)


@app.post("/api/imports")
async def api_import_source(
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
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    finally:
        temp_path.unlink(missing_ok=True)


@app.get("/api/imports/{import_id}")
def api_get_import(import_id: str) -> dict:
    try:
        return get_import_detail(settings(), import_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/imports/{import_id}/approve")
def api_approve_import(import_id: str, payload: ApproveRequest) -> dict:
    try:
        return approve_import_by_id(
            settings(),
            import_id,
            payload.approved_by,
            carrier_name=payload.carrier_name,
            carrier_key=payload.carrier_key,
            carrier_label=payload.carrier_label,
            contract_tag=payload.contract_tag,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/imports/{import_id}/reject")
def api_reject_import(import_id: str, payload: RejectRequest) -> dict:
    try:
        return reject_import_by_id(settings(), import_id, payload.reason)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.delete("/api/imports/{import_id}")
def api_delete_import(import_id: str) -> dict:
    try:
        return delete_import_by_id(settings(), import_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/search")
def api_search(
    provider_name: str | None = None,
    carrier_name: str | None = None,
    pol: str | None = None,
    pod: str | None = None,
    equipment_type: str | None = None,
    valid_on: str | None = None,
    limit: int = 200,
) -> list[dict]:
    return search_approved_offers(
        settings(),
        provider_name=provider_name,
        carrier_name=carrier_name,
        pol=pol,
        pod=pod,
        equipment_type=equipment_type,
        valid_on=valid_on,
        limit=limit,
    )


@app.get("/api/rate-desk")
def api_rate_desk(limit: int = 2000) -> dict:
    return get_rate_desk_data(settings(), limit=min(max(limit, 1), 5000))


ui_dir = Path(__file__).resolve().parents[1] / "UI"
if ui_dir.exists():
    app.mount("/ui", StaticFiles(directory=ui_dir, html=True), name="ui")
