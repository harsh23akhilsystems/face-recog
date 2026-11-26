"""FastAPI application: REST API under ``/api/v1`` plus the static web console at ``/``.

The service is created once at startup (``lifespan``) and stored on ``app.state`` so tests can
inject a service built from fakes via ``create_app(service=...)``. Inference endpoints are plain
``def`` handlers so FastAPI runs them in its threadpool and the event loop stays responsive.
"""

from __future__ import annotations

import logging
import sqlite3
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Annotated

import numpy as np
from fastapi import APIRouter, Depends, FastAPI, File, Form, HTTPException, Query, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from facegate import __version__
from facegate.api.schemas import PersonCreate, PersonUpdate, RuntimeSettingsPatch
from facegate.config import get_settings
from facegate.service import FaceService
from facegate.vision.pipeline import decode_image

log = logging.getLogger(__name__)
FRONTEND_DIR = Path(__file__).resolve().parents[3] / "frontend"


def get_service(request: Request) -> FaceService:
    return request.app.state.service


Svc = Annotated[FaceService, Depends(get_service)]


def read_image(svc: FaceService, upload: UploadFile) -> np.ndarray:
    limit = svc.settings.api.max_upload_mb * 1024 * 1024
    data = upload.file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(413, f"{upload.filename or 'file'} exceeds {svc.settings.api.max_upload_mb} MB")
    try:
        return decode_image(data)
    except ValueError as exc:
        raise HTTPException(422, f"{upload.filename or 'file'}: {exc}") from exc


def require_ready(svc: FaceService) -> None:
    if not svc.pipeline.ready:
        missing = [s.file for s in svc.pipeline.status() if s.enabled and not s.loaded]
        raise HTTPException(503, f"Models not loaded: {', '.join(missing) or 'none'}. See README → Models.")


router = APIRouter(prefix="/api/v1")


# ---------------------------------------------------------------------- system
@router.get("/health", tags=["system"])
def health(svc: Svc) -> dict:
    return svc.health() | {
        "version": __version__,
        "app": svc.settings.app.name,
        "organisation": svc.settings.app.organisation,
    }


@router.get("/stats", tags=["system"])
def stats(svc: Svc) -> dict:
    return svc.store.stats()


@router.get("/settings", tags=["system"])
def get_runtime_settings(svc: Svc) -> dict:
    return svc.get_runtime_settings()


@router.put("/settings", tags=["system"])
def put_runtime_settings(body: RuntimeSettingsPatch, svc: Svc) -> dict:
    return svc.update_runtime_settings(body.model_dump(exclude_none=True))


@router.post("/admin/reembed", tags=["system"])
def reembed(svc: Svc) -> dict:
    require_ready(svc)
    return svc.reembed()


# ---------------------------------------------------------------------- inference
@router.post("/detect", tags=["inference"])
def detect(svc: Svc, image: UploadFile = File(...)) -> dict:
    if svc.pipeline.detector is None:
        require_ready(svc)
    return svc.detect(read_image(svc, image))


@router.post("/recognize", tags=["inference"])
def recognize(
    svc: Svc,
    image: UploadFile = File(...),
    mode: str | None = Form(None),
    source: str = Form("upload"),
    log_events: bool | None = Form(None),
) -> dict:
    require_ready(svc)
    if mode not in (None, "", "arcface", "adaface", "fusion", "strict"):
        raise HTTPException(422, f"Unknown mode {mode!r}")
    return svc.recognize(read_image(svc, image), mode or None, source[:32], log_events)


@router.post("/verify", tags=["inference"])
def verify(svc: Svc, image_a: UploadFile = File(...), image_b: UploadFile = File(...)) -> dict:
    require_ready(svc)
    try:
        return svc.verify(read_image(svc, image_a), read_image(svc, image_b))
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


# ---------------------------------------------------------------------- people
@router.get("/people", tags=["people"])
def list_people(svc: Svc, q: str | None = None) -> list[dict]:
    return svc.store.list_people(query=q)


@router.post("/people", status_code=201, tags=["people"])
def create_person(body: PersonCreate, svc: Svc) -> dict:
    try:
        return svc.store.create_person(**body.model_dump())
    except sqlite3.IntegrityError as exc:
        raise HTTPException(409, f"Employee ID {body.employee_id!r} is already registered") from exc


def _person_or_404(svc: FaceService, pid: str) -> dict:
    person = svc.store.get_person(pid)
    if person is None:
        raise HTTPException(404, "Person not found")
    return person


@router.get("/people/{pid}", tags=["people"])
def get_person(pid: str, svc: Svc) -> dict:
    return _person_or_404(svc, pid) | {"samples": svc.store.list_samples(pid)}


@router.patch("/people/{pid}", tags=["people"])
def update_person(pid: str, body: PersonUpdate, svc: Svc) -> dict:
    _person_or_404(svc, pid)
    try:
        return svc.store.update_person(pid, **body.model_dump(exclude_unset=True))  # type: ignore[return-value]
    except sqlite3.IntegrityError as exc:
        raise HTTPException(409, f"Employee ID {body.employee_id!r} is already registered") from exc


@router.delete("/people/{pid}", status_code=204, tags=["people"])
def delete_person(pid: str, svc: Svc) -> Response:
    if not svc.store.delete_person(pid):
        raise HTTPException(404, "Person not found")
    return Response(status_code=204)


@router.post("/people/{pid}/samples", tags=["people"])
def enroll(pid: str, svc: Svc, images: list[UploadFile] = File(...)) -> dict:
    require_ready(svc)
    _person_or_404(svc, pid)
    decoded, rejected = [], []
    for up in images:
        try:
            decoded.append((up.filename or "image", read_image(svc, up)))
        except HTTPException as exc:
            rejected.append({"filename": up.filename, "accepted": False, "reason": exc.detail, "warnings": []})
    outcomes = [asdict(o) for o in svc.enroll(pid, decoded)] + rejected
    return {"accepted": sum(o["accepted"] for o in outcomes), "results": outcomes, "person": svc.store.get_person(pid)}


@router.delete("/people/{pid}/samples/{sid}", status_code=204, tags=["people"])
def delete_sample(pid: str, sid: str, svc: Svc) -> Response:
    if not svc.store.delete_sample(sid, person_id=pid):
        raise HTTPException(404, "Sample not found")
    return Response(status_code=204)


@router.get("/samples/{sid}/thumb", tags=["people"], response_class=Response)
def sample_thumb(sid: str, svc: Svc) -> Response:
    data = svc.store.get_thumb(sid)
    if not data:
        raise HTTPException(404, "No thumbnail")
    return Response(data, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=86400"})


# ---------------------------------------------------------------------- events
@router.get("/events", tags=["events"])
def list_events(
    svc: Svc,
    limit: int = Query(50, ge=1, le=500),
    status: str | None = Query(None, pattern="^(match|unknown|uncertain)$"),
    person_id: str | None = None,
    since: str | None = None,
) -> list[dict]:
    return svc.store.list_events(limit, status, person_id, since)


@router.get("/events/{eid}/thumb", tags=["events"], response_class=Response)
def event_thumb(eid: int, svc: Svc) -> Response:
    data = svc.store.get_event_thumb(eid)
    if not data:
        raise HTTPException(404, "No thumbnail")
    return Response(data, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=86400"})


# ---------------------------------------------------------------------- app factory
def create_app(service: FaceService | None = None) -> FastAPI:
    settings = service.settings if service else get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if getattr(app.state, "service", None) is None:
            app.state.service = FaceService.from_settings(settings)
        yield
        app.state.service.store.close()

    app = FastAPI(
        title=f"{settings.app.name} API",
        version=__version__,
        lifespan=lifespan,
        description="Face detection (SCRFD) and recognition (ArcFace + AdaFace).",
    )
    app.state.service = service
    if settings.api.cors_origins:
        app.add_middleware(
            CORSMiddleware, allow_origins=settings.api.cors_origins, allow_methods=["*"], allow_headers=["*"]
        )
    app.include_router(router)

    @app.middleware("http")
    async def revalidate_assets(request: Request, call_next):
        # The console has no build step / hashed filenames, so make browsers revalidate (ETag) on every load.
        response = await call_next(request)
        if request.url.path.startswith("/assets/"):
            response.headers.setdefault("Cache-Control", "no-cache")
        return response

    if FRONTEND_DIR.exists():
        app.mount("/assets", StaticFiles(directory=FRONTEND_DIR / "assets"), name="assets")

        @app.get("/", include_in_schema=False)
        def index() -> FileResponse:
            return FileResponse(FRONTEND_DIR / "index.html", headers={"Cache-Control": "no-cache"})

    return app


app = create_app()
