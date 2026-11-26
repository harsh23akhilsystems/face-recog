"""FastAPI application: REST API under ``/api/v1``, sign-in under ``/auth``, the login page at ``/login`` and the
static web console at ``/``.

Every ``/api/v1`` route except ``/health`` requires a signed-in session (cookie); ``/`` redirects to ``/login``
when there is none. ``/health`` stays public for monitoring but hides gallery details from anonymous callers.

The service is created once at startup (``lifespan``) and stored on ``app.state`` so tests can
inject a service built from fakes via ``create_app(service=...)``. Inference endpoints are plain
``def`` handlers so FastAPI runs them in its threadpool and the event loop stays responsive.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path

from fastapi import APIRouter, Depends, FastAPI, File, Form, HTTPException, Query, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from facegate import __version__
from facegate.api import auth_routes
from facegate.api.deps import Auth, Svc, current_session, read_image, session_of
from facegate.api.schemas import PersonCreate, PersonUpdate, RuntimeSettingsPatch
from facegate.auth import AuthService
from facegate.config import get_settings
from facegate.service import FaceService

log = logging.getLogger(__name__)
FRONTEND_DIR = Path(__file__).resolve().parents[3] / "frontend"


def require_ready(svc: FaceService) -> None:
    if not svc.pipeline.ready:
        missing = [s.file for s in svc.pipeline.status() if s.enabled and not s.loaded]
        raise HTTPException(503, f"Models not loaded: {', '.join(missing) or 'none'}. See README → Models.")


public = APIRouter(prefix="/api/v1")
router = APIRouter(prefix="/api/v1", dependencies=[Depends(current_session)])


# ---------------------------------------------------------------------- system
@public.get("/health", tags=["system"])
def health(request: Request, svc: Svc, auth: Auth) -> dict:
    h = svc.health()
    base = {"status": h["status"], "ready": h["ready"], "version": __version__, "app": svc.settings.app.name}
    if session_of(request, auth) is None:
        return base | {"signed_in": False}
    return h | base | {"organisation": svc.settings.app.organisation, "signed_in": True}


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
def detect(svc: Svc, image: UploadFile = File(...), size: int | None = Form(None, ge=96, le=1280)) -> dict:
    if svc.pipeline.detector is None:
        require_ready(svc)
    return svc.detect(read_image(svc, image), size)


@router.get("/enrollment/guide", tags=["people"])
def enrollment_guide(svc: Svc) -> dict:
    return svc.enrollment_guide()


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
        raise HTTPException(409, _employee_taken(svc, body.employee_id)) from exc


def _employee_taken(svc: FaceService, employee_id: str | None) -> str:
    owner = next((p for p in svc.store.list_people(query=employee_id) if p.get("employee_id") == employee_id), None)
    who = f" to {owner['name']}" if owner else ""
    return f"Employee ID {employee_id!r} is already registered{who}"


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
    sid = body.profile_sample_id
    if sid and not any(s["id"] == sid for s in svc.store.list_samples(pid)):
        raise HTTPException(422, "That photo does not belong to this person")
    try:
        return svc.store.update_person(pid, **body.model_dump(exclude_unset=True))  # type: ignore[return-value]
    except sqlite3.IntegrityError as exc:
        raise HTTPException(409, _employee_taken(svc, body.employee_id)) from exc


@router.delete("/people/{pid}", status_code=204, tags=["people"])
def delete_person(pid: str, svc: Svc) -> Response:
    if not svc.store.delete_person(pid):
        raise HTTPException(404, "Person not found")
    return Response(status_code=204)


def _enroll_uploads(svc: FaceService, pid: str, images: list[UploadFile], dry_run: bool) -> dict:
    require_ready(svc)
    _person_or_404(svc, pid)
    # Results stay in upload order (the console maps them back to its photos by index), undecodable files included.
    slots: list[dict | None] = []
    decoded = []
    for up in images:
        try:
            decoded.append((up.filename or "image", read_image(svc, up)))
            slots.append(None)
        except HTTPException as exc:
            slots.append({"filename": up.filename, "accepted": False, "reason": exc.detail, "warnings": []})
    done = iter(asdict(o) for o in svc.enroll(pid, decoded, dry_run=dry_run))
    outcomes = [s if s is not None else next(done) for s in slots]
    return {"accepted": sum(o["accepted"] for o in outcomes), "results": outcomes, "person": svc.store.get_person(pid)}


@router.post("/people/{pid}/samples", tags=["people"])
def enroll(pid: str, svc: Svc, images: list[UploadFile] = File(...)) -> dict:
    return _enroll_uploads(svc, pid, images, dry_run=False)


@router.post("/people/{pid}/samples/check", tags=["people"])
def check_samples(pid: str, svc: Svc, images: list[UploadFile] = File(...)) -> dict:
    """Run every enrollment gate on the photos without storing anything (same response shape as enroll)."""
    return _enroll_uploads(svc, pid, images, dry_run=True)


@router.post("/people/{pid}/duplicate-check", tags=["people"])
def duplicate_check(pid: str, svc: Svc, image: UploadFile = File(...)) -> dict:
    require_ready(svc)
    _person_or_404(svc, pid)
    return svc.check_duplicate(read_image(svc, image), pid)


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
def _safe_backfill(svc: FaceService) -> None:
    try:
        svc.backfill_poses()
    except Exception:  # never let a maintenance task take the server down
        log.exception("Pose backfill failed")


def create_app(service: FaceService | None = None) -> FastAPI:
    settings = service.settings if service else get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if getattr(app.state, "service", None) is None:
            app.state.service = FaceService.from_settings(settings)
            # One-off, in the background: older samples get a head pose so their profile photo can be frontal.
            threading.Thread(target=_safe_backfill, args=(app.state.service,), daemon=True).start()
        app.state.auth = AuthService(app.state.service)
        created = app.state.auth.bootstrap_admin()
        if created:
            log.warning("First start: user 'admin' created; its password is in %s — sign in, then delete it", created)
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
    app.include_router(public)
    app.include_router(router)
    app.include_router(auth_routes.router)

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
        def index(request: Request, auth: Auth) -> Response:
            if session_of(request, auth) is None:
                return RedirectResponse("/login", status_code=303)
            return FileResponse(FRONTEND_DIR / "index.html", headers={"Cache-Control": "no-cache"})

        @app.get("/login", include_in_schema=False)
        def login_page(request: Request, auth: Auth) -> Response:
            if session_of(request, auth) is not None:
                return RedirectResponse("/", status_code=303)
            return FileResponse(FRONTEND_DIR / "login.html", headers={"Cache-Control": "no-cache"})

    return app


app = create_app()
