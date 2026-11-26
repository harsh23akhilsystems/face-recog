"""Console sign-in: user accounts, server-side sessions, a login audit log, and face sign-in.

Ported from the Augastam face service and rebuilt on FaceGate's own models:

- **Passwords**: PBKDF2-SHA256 (stdlib) with a per-user salt; unknown usernames still pay the hashing cost so
  response time does not reveal which accounts exist.
- **Sessions**: random token in an HttpOnly cookie; only its SHA-256 is stored, so sessions can be revoked and a
  leaked database does not leak live tokens.
- **Face sign-in**: a user account is *linked* to a person in the FaceGate gallery (``users.person_id``). Signing
  in runs the normal pipeline + matcher (``auth.face_mode``, strict by default) and accepts only a ``match`` on a
  linked, active person. There is no second set of face templates — enrolling photos on the People page is
  what makes face sign-in work, and deleting the person removes it.
- **Lockout**: failures are counted from the audit log per username (password) and per client IP (face).

The tables live in the gallery's SQLite file and share its connection and lock.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import os
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np

from facegate import quality
from facegate.service import FaceService

log = logging.getLogger(__name__)

ROLES = ("admin", "staff")

AUTH_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT NOT NULL UNIQUE COLLATE NOCASE,
    display_name  TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    role          TEXT NOT NULL DEFAULT 'staff',      -- admin | staff
    person_id     TEXT REFERENCES people(id) ON DELETE SET NULL,  -- gallery person used for face sign-in
    active        INTEGER NOT NULL DEFAULT 1,
    created_at    TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_users_person ON users(person_id) WHERE person_id IS NOT NULL;
CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    method     TEXT NOT NULL,                         -- password | face
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS login_events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    ts         TEXT NOT NULL,
    method     TEXT NOT NULL,                         -- password | face | logout
    username   TEXT,
    user_id    INTEGER,
    outcome    TEXT NOT NULL,                         -- success | failed | rejected | locked
    reason     TEXT,
    score      REAL,
    client     TEXT
);
CREATE INDEX IF NOT EXISTS ix_login_events_ts ON login_events(ts);
"""


class AuthError(Exception):
    """A sign-in failure with the HTTP status and the message to show the user."""

    def __init__(self, status: int, message: str, quality: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.message = message
        self.quality = quality  # framing feedback for the login camera on a 422


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(d: datetime) -> str:
    return d.isoformat(timespec="seconds")


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def hash_password(password: str, iterations: int) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)
    return f"pbkdf2_sha256${iterations}${base64.b64encode(salt).decode()}${base64.b64encode(dk).decode()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, it, salt, dk = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        calc = hashlib.pbkdf2_hmac("sha256", password.encode(), base64.b64decode(salt), int(it))
        return hmac.compare_digest(calc, base64.b64decode(dk))
    except (ValueError, TypeError):
        return False


@dataclass
class User:
    id: int
    username: str
    display_name: str
    role: str
    person_id: str | None
    created_at: str

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

    def public(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "username": self.username,
            "display_name": self.display_name,
            "role": self.role,
            "person_id": self.person_id,
            "face_login": self.person_id is not None,
            "created_at": self.created_at,
        }


def _user(row: Any) -> User | None:
    if row is None:
        return None
    return User(row["id"], row["username"], row["display_name"], row["role"], row["person_id"], row["created_at"])


class AuthService:
    def __init__(self, face: FaceService) -> None:
        self.face = face
        self.cfg = face.settings.auth
        self.store = face.store
        self._dummy_hash = hash_password(secrets.token_hex(8), self.cfg.password_iterations)
        with self.store._tx() as c:
            c.executescript(AUTH_SCHEMA)
            c.execute("DELETE FROM sessions WHERE expires_at <= ?", (_iso(_now()),))

    # ------------------------------------------------------------------ db helpers
    def _one(self, sql: str, args: tuple = ()) -> Any:
        with self.store._lock:
            return self.store._conn.execute(sql, args).fetchone()

    def _all(self, sql: str, args: tuple = ()) -> list[Any]:
        with self.store._lock:
            return self.store._conn.execute(sql, args).fetchall()

    # ------------------------------------------------------------------ users
    def user_count(self) -> int:
        return self._one("SELECT COUNT(*) FROM users")[0]

    def get_user(self, user_id: int) -> User | None:
        return _user(self._one("SELECT * FROM users WHERE id = ? AND active = 1", (user_id,)))

    def get_by_username(self, username: str) -> User | None:
        return _user(self._one("SELECT * FROM users WHERE username = ? AND active = 1", (username.strip(),)))

    def list_users(self) -> list[dict[str, Any]]:
        rows = self._all(
            "SELECT u.*, p.name AS person_name FROM users u LEFT JOIN people p ON p.id = u.person_id"
            " WHERE u.active = 1 ORDER BY u.username COLLATE NOCASE"
        )
        return [_user(r).public() | {"person_name": r["person_name"]} for r in rows]  # type: ignore[union-attr]

    def _validate(self, password: str | None, role: str | None, person_id: str | None, user_id: int | None) -> None:
        if password is not None and len(password) < self.cfg.password_min_length:
            raise ValueError(f"Password must be at least {self.cfg.password_min_length} characters")
        if role is not None and role not in ROLES:
            raise ValueError(f"Role must be one of: {', '.join(ROLES)}")
        if person_id:
            if self.store.get_person(person_id) is None:
                raise ValueError("Gallery person not found")
            other = self._one("SELECT id FROM users WHERE person_id = ? AND active = 1", (person_id,))
            if other and other["id"] != user_id:
                raise ValueError("That person is already linked to another user")

    def create_user(
        self,
        username: str,
        password: str,
        display_name: str | None = None,
        role: str = "staff",
        person_id: str | None = None,
    ) -> User:
        username = username.strip()
        if not username:
            raise ValueError("Username is required")
        self._validate(password, role, person_id, None)
        if self._one("SELECT 1 FROM users WHERE username = ?", (username,)):
            raise ValueError(f"Username {username!r} is already taken")
        with self.store._tx() as c:
            cur = c.execute(
                "INSERT INTO users (username, display_name, password_hash, role, person_id, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (
                    username,
                    (display_name or "").strip() or username,
                    hash_password(password, self.cfg.password_iterations),
                    role,
                    person_id or None,
                    _iso(_now()),
                ),
            )
        return self.get_user(cur.lastrowid)  # type: ignore[arg-type,return-value]

    def update_user(self, user_id: int, **fields: Any) -> User:
        """Update any of display_name, role, person_id ("" unlinks) or password; password change ends sessions."""
        if self.get_user(user_id) is None:
            raise KeyError(user_id)
        person_id = fields.get("person_id")
        self._validate(fields.get("password"), fields.get("role"), person_id or None, user_id)
        sets: dict[str, Any] = {}
        if fields.get("display_name"):
            sets["display_name"] = fields["display_name"].strip()
        if fields.get("role"):
            sets["role"] = fields["role"]
        if "person_id" in fields and person_id is not None:
            sets["person_id"] = person_id or None
        if fields.get("password"):
            sets["password_hash"] = hash_password(fields["password"], self.cfg.password_iterations)
        if sets:
            cols = ", ".join(f"{k} = ?" for k in sets)
            with self.store._tx() as c:
                c.execute(f"UPDATE users SET {cols} WHERE id = ?", (*sets.values(), user_id))
                if "password_hash" in sets:
                    c.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
        return self.get_user(user_id)  # type: ignore[return-value]

    def deactivate_user(self, user_id: int) -> bool:
        """Soft delete: keeps the audit trail, ends sessions, frees the username link to the gallery person."""
        with self.store._tx() as c:
            cur = c.execute("UPDATE users SET active = 0, person_id = NULL WHERE id = ? AND active = 1", (user_id,))
            c.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
        return cur.rowcount > 0

    def active_admins(self) -> int:
        return self._one("SELECT COUNT(*) FROM users WHERE role = 'admin' AND active = 1")[0]

    def bootstrap_admin(self) -> Path | None:
        """First start only: create ``admin`` with a random password written to a private local file."""
        if self.user_count():
            return None
        password = secrets.token_urlsafe(12)
        self.create_user("admin", password, "Administrator", role="admin")
        path = self.face.settings.data_dir / "initial_admin_credentials.txt"
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)  # owner-only from the first byte
        with os.fdopen(fd, "w") as fh:
            fh.write("Created on first start. Sign in, then delete this file.\n")
            fh.write(f"username: admin\npassword: {password}\n")
        return path

    # ------------------------------------------------------------------ audit + lockout
    def log(
        self,
        method: str,
        outcome: str,
        *,
        username: str | None = None,
        user_id: int | None = None,
        reason: str | None = None,
        score: float | None = None,
        client: str | None = None,
    ) -> None:
        with self.store._tx() as c:
            c.execute(
                "INSERT INTO login_events (ts, method, username, user_id, outcome, reason, score, client)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    _iso(_now()),
                    method,
                    username,
                    user_id,
                    outcome,
                    reason[:200] if reason else None,
                    None if score is None else round(float(score), 4),
                    client,
                ),
            )

    def events(self, limit: int = 50) -> list[dict[str, Any]]:
        return [dict(r) for r in self._all("SELECT * FROM login_events ORDER BY id DESC LIMIT ?", (limit,))]

    def recent_failures(self, method: str, *, username: str | None = None, client: str | None = None) -> int:
        sql = "SELECT COUNT(*) FROM login_events WHERE outcome = 'failed' AND method = ? AND ts >= ?"
        args: list[Any] = [method, _iso(_now() - timedelta(minutes=self.cfg.lock_window_minutes))]
        if username is not None:
            sql += " AND username = ? COLLATE NOCASE"
            args.append(username.strip())
        if client is not None:
            sql += " AND client = ?"
            args.append(client)
        return self._one(sql, tuple(args))[0]

    # ------------------------------------------------------------------ sessions
    def create_session(self, user: User, method: str) -> str:
        token, now = secrets.token_urlsafe(32), _now()
        with self.store._tx() as c:
            c.execute(
                "INSERT INTO sessions (token_hash, user_id, method, created_at, expires_at) VALUES (?, ?, ?, ?, ?)",
                (_token_hash(token), user.id, method, _iso(now), _iso(now + timedelta(hours=self.cfg.session_hours))),
            )
        return token

    def session_user(self, token: str | None) -> tuple[User, str] | None:
        if not token:
            return None
        row = self._one(
            "SELECT u.*, s.method AS s_method FROM sessions s JOIN users u ON u.id = s.user_id"
            " WHERE s.token_hash = ? AND s.expires_at > ? AND u.active = 1",
            (_token_hash(token), _iso(_now())),
        )
        return (_user(row), row["s_method"]) if row else None  # type: ignore[return-value]

    def end_session(self, token: str | None) -> None:
        if token:
            with self.store._tx() as c:
                c.execute("DELETE FROM sessions WHERE token_hash = ?", (_token_hash(token),))

    # ------------------------------------------------------------------ password sign-in
    def password_login(self, username: str, password: str, client: str | None) -> User:
        if self.recent_failures("password", username=username) >= self.cfg.max_failed_per_user:
            self.log("password", "locked", username=username, reason="too many failed attempts", client=client)
            raise AuthError(429, f"Too many failed attempts. Try again in {self.cfg.lock_window_minutes} minutes.")
        row = self._one("SELECT * FROM users WHERE username = ? AND active = 1", (username.strip(),))
        if row is None:
            verify_password(password, self._dummy_hash)  # equalise timing for unknown users
        if row is None or not verify_password(password, row["password_hash"]):
            self.log("password", "failed", username=username, reason="bad credentials", client=client)
            raise AuthError(401, "Invalid username or password.")
        user = _user(row)
        self.log("password", "success", username=user.username, user_id=user.id, client=client)  # type: ignore[union-attr]
        return user  # type: ignore[return-value]

    # ------------------------------------------------------------------ face sign-in
    def face_status(self) -> dict[str, Any]:
        """Public: lets the login page show or hide the face option. Contains no user data."""
        linked = self._one(
            "SELECT COUNT(*) FROM users u JOIN samples s ON s.person_id = u.person_id"
            " JOIN people p ON p.id = u.person_id WHERE u.active = 1 AND p.active = 1"
        )[0]
        return {
            "available": self.cfg.face_login and self.face.pipeline.ready,
            "any_enrolled": linked > 0,
            "liveness": self.face.pipeline.liveness is not None and self.cfg.liveness.mode != "off",
        }

    def quality(self, img: np.ndarray) -> dict[str, Any]:
        if self.face.pipeline.detector is None:
            raise AuthError(503, "Face sign-in is not available: the face detector is not loaded.")
        return quality.analyze(img, self.face.pipeline.detect(img, self.cfg.detect_size), self.cfg.quality)

    def face_login(self, img: np.ndarray, client: str | None) -> tuple[User, float]:
        pipeline = self.face.pipeline
        if not self.cfg.face_login:
            raise AuthError(403, "Face sign-in is turned off.")
        if not pipeline.ready:
            raise AuthError(503, "Face sign-in is not available: recognition models are not loaded.")
        if self.recent_failures("face", client=client) >= self.cfg.max_failed_face_per_client:
            self.log("face", "locked", reason="too many failed face attempts", client=client)
            raise AuthError(
                429,
                f"Too many failed face attempts. Sign in with your password or wait {self.cfg.lock_window_minutes}"
                " minutes.",
            )

        # Detect + quality first and recognise only frames that pass: the login camera sends frames continuously,
        # so a badly framed frame costs one detection (no ArcFace) and returns the advice + face box at once.
        faces = pipeline.detect(img, self.cfg.detect_size)
        q = quality.analyze(img, faces, self.cfg.quality)
        if not q["ok"]:  # framing problems are guidance, not failed attempts (and not logged: one per frame)
            raise AuthError(422, q["advice"][0], quality=q)
        face = next(f for f in faces if f.score >= self.cfg.quality.min_det_score)
        pipeline.embed(img, [face])

        lv = pipeline.check_liveness(img, face.bbox) if self.cfg.liveness.mode != "off" else None
        lv_note = f"liveness {lv['score']}" if lv else "liveness unavailable"
        if lv and not lv["real"] and self.cfg.liveness.mode == "enforce":
            self.log("face", "failed", reason=f"spoof suspected ({lv_note})", client=client)
            raise AuthError(401, "Liveness check failed. Use your live face — photos and screens aren't accepted.")

        res = self.face.matcher.identify(face.embeddings, self.cfg.face_mode)
        user = None
        if res.status == "match" and res.person_id:
            user = _user(self._one("SELECT * FROM users WHERE person_id = ? AND active = 1", (res.person_id,)))
        if user is None:
            why = f"{res.status}" if res.status != "match" else "matched person has no linked account"
            self.log("face", "failed", reason=f"{why}; {lv_note}", score=res.score, client=client)
            raise AuthError(401, "Face not recognised. Try again or sign in with your password.")
        self.log(
            "face", "success", username=user.username, user_id=user.id, reason=lv_note, score=res.score, client=client
        )
        return user, res.score
