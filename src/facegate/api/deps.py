"""Request dependencies shared by the REST routers: service lookup, upload decoding and the session guard.

Kept apart from ``main.py`` so ``auth_routes.py`` can use them without a circular import.
"""

from __future__ import annotations

from typing import Annotated

import numpy as np
from fastapi import Depends, HTTPException, Request, UploadFile

from facegate.auth import AuthService, User
from facegate.service import FaceService
from facegate.vision.pipeline import decode_image


def get_service(request: Request) -> FaceService:
    return request.app.state.service


def get_auth(request: Request) -> AuthService:
    return request.app.state.auth


Svc = Annotated[FaceService, Depends(get_service)]
Auth = Annotated[AuthService, Depends(get_auth)]


def read_image(svc: FaceService, upload: UploadFile) -> np.ndarray:
    limit = svc.settings.api.max_upload_mb * 1024 * 1024
    data = upload.file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(413, f"{upload.filename or 'file'} exceeds {svc.settings.api.max_upload_mb} MB")
    try:
        return decode_image(data)
    except ValueError as exc:
        raise HTTPException(422, f"{upload.filename or 'file'}: {exc}") from exc


def client_id(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def session_of(request: Request, auth: AuthService) -> tuple[User, str] | None:
    return auth.session_user(request.cookies.get(auth.cfg.cookie_name))


def current_session(request: Request, auth: Auth) -> tuple[User, str]:
    s = session_of(request, auth)
    if s is None:
        raise HTTPException(401, "Not signed in")
    return s


Session = Annotated[tuple[User, str], Depends(current_session)]


def admin_session(s: Session) -> tuple[User, str]:
    """User management needs the admin role AND a password session (a face session cannot manage accounts)."""
    user, method = s
    if not user.is_admin:
        raise HTTPException(403, "Only administrators can manage users.")
    if method != "password":
        raise HTTPException(403, "Sign in with your password to manage users.")
    return s


AdminSession = Annotated[tuple[User, str], Depends(admin_session)]
