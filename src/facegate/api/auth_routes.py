"""Sign-in endpoints under ``/auth``: password and face sign-in, session, live quality check, user admin.

``/auth/login``, ``/auth/face``, ``/auth/quality`` and ``/auth/face/status`` are public because the login page
needs them before anyone is signed in; everything else requires a session.
"""

from __future__ import annotations

from fastapi import APIRouter, File, HTTPException, Query, Request, Response, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from facegate.api.deps import AdminSession, Auth, Session, Svc, client_id, read_image, session_of
from facegate.auth import AuthError, AuthService, User

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginBody(BaseModel):
    username: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=1, max_length=256)


class UserCreate(BaseModel):
    username: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=1, max_length=256)
    display_name: str | None = Field(default=None, max_length=120)
    role: str = "staff"
    person_id: str | None = None


class UserUpdate(BaseModel):
    display_name: str | None = Field(default=None, max_length=120)
    role: str | None = None
    person_id: str | None = None  # "" unlinks face sign-in
    password: str | None = Field(default=None, max_length=256)


def _sign_in(response: Response, auth: AuthService, user: User, method: str) -> dict:
    token = auth.create_session(user, method)
    response.set_cookie(
        auth.cfg.cookie_name,
        token,
        max_age=auth.cfg.session_hours * 3600,
        httponly=True,
        samesite="lax",
        secure=auth.cfg.cookie_secure,
        path="/",
    )
    return {"user": user.public(), "method": method}


def _raise(exc: AuthError) -> HTTPException:
    return HTTPException(exc.status, exc.message)


@router.post("/login")
def login(body: LoginBody, request: Request, response: Response, auth: Auth) -> dict:
    try:
        user = auth.password_login(body.username, body.password, client_id(request))
    except AuthError as exc:
        raise _raise(exc) from exc
    return _sign_in(response, auth, user, "password")


@router.post("/face")
def face_login(request: Request, response: Response, auth: Auth, svc: Svc, image: UploadFile = File(...)):
    """One camera frame. 200 = signed in; 422 = framing advice + ``quality`` (face box) to try the next frame."""
    img = read_image(svc, image)
    try:
        user, score = auth.face_login(img, client_id(request))
    except AuthError as exc:
        if exc.quality is not None:
            return JSONResponse({"detail": exc.message, "quality": exc.quality}, status_code=exc.status)
        raise _raise(exc) from exc
    return _sign_in(response, auth, user, "face") | {"score": round(score, 4)}


@router.post("/quality")
def check_quality(auth: Auth, svc: Svc, image: UploadFile = File(...)) -> dict:
    """Framing/lighting guidance for the login camera. Nothing is stored."""
    try:
        return auth.quality(read_image(svc, image))
    except AuthError as exc:
        raise _raise(exc) from exc


@router.get("/face/status")
def face_status(auth: Auth) -> dict:
    return auth.face_status()


@router.post("/logout")
def logout(request: Request, response: Response, auth: Auth) -> dict:
    s = session_of(request, auth)
    auth.end_session(request.cookies.get(auth.cfg.cookie_name))
    if s:
        auth.log("logout", "success", username=s[0].username, user_id=s[0].id, client=client_id(request))
    response.delete_cookie(auth.cfg.cookie_name, path="/")
    return {"ok": True}


@router.get("/me")
def me(s: Session, auth: Auth) -> dict:
    user, method = s
    return {"user": user.public(), "method": method, "face": auth.face_status()}


# ---------------------------------------------------------------------- admin
@router.get("/events")
def login_events(_: AdminSession, auth: Auth, limit: int = Query(50, ge=1, le=500)) -> list[dict]:
    return auth.events(limit)


@router.get("/users")
def list_users(_: AdminSession, auth: Auth) -> list[dict]:
    return auth.list_users()


@router.post("/users", status_code=201)
def create_user(body: UserCreate, _: AdminSession, auth: Auth) -> dict:
    try:
        return auth.create_user(**body.model_dump()).public()
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.patch("/users/{user_id}")
def update_user(user_id: int, body: UserUpdate, s: AdminSession, auth: Auth) -> dict:
    target = auth.get_user(user_id)
    if target is None:
        raise HTTPException(404, "User not found")
    if target.is_admin and body.role == "staff" and auth.active_admins() <= 1:
        raise HTTPException(409, "Cannot demote the last administrator")
    try:
        return auth.update_user(user_id, **body.model_dump(exclude_unset=True)).public()
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.delete("/users/{user_id}", status_code=204)
def delete_user(user_id: int, s: AdminSession, auth: Auth) -> Response:
    if user_id == s[0].id:
        raise HTTPException(409, "You cannot remove your own account")
    if not auth.deactivate_user(user_id):
        raise HTTPException(404, "User not found")
    return Response(status_code=204)
