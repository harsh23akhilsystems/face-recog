"""SQLite persistence for people, face samples, embeddings and recognition events.

Why SQLite: a single file that a company IT team can back up, encrypt at rest and audit, with
no extra service to run. Embeddings are stored per *sample* and per *model*, so enabling a new
recognizer later only requires re-embedding stored thumbnails (``facegate reembed``), never
re-photographing staff.

Raw uploaded photos are never stored — only the 112x112 aligned crop (optional) and vectors.
"""

from __future__ import annotations

import sqlite3
import threading
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np

SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS people (
    id           TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    employee_id  TEXT UNIQUE,
    department   TEXT,
    notes        TEXT,
    active       INTEGER NOT NULL DEFAULT 1,
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS samples (
    id          TEXT PRIMARY KEY,
    person_id   TEXT NOT NULL REFERENCES people(id) ON DELETE CASCADE,
    det_score   REAL NOT NULL,
    sharpness   REAL NOT NULL,
    face_px     REAL NOT NULL,
    thumb       BLOB,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_samples_person ON samples(person_id);
CREATE TABLE IF NOT EXISTS embeddings (
    sample_id  TEXT NOT NULL REFERENCES samples(id) ON DELETE CASCADE,
    model      TEXT NOT NULL,
    dim        INTEGER NOT NULL,
    vector     BLOB NOT NULL,
    PRIMARY KEY (sample_id, model)
);
CREATE TABLE IF NOT EXISTS events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          TEXT NOT NULL,
    person_id   TEXT REFERENCES people(id) ON DELETE SET NULL,
    name        TEXT,
    status      TEXT NOT NULL,          -- match | unknown | uncertain
    score       REAL,
    mode        TEXT NOT NULL,
    source      TEXT NOT NULL,
    thumb       BLOB
);
CREATE INDEX IF NOT EXISTS ix_events_ts ON events(ts);
"""

# Columns added after the first release; created on open when missing (SQLite has no ADD COLUMN IF NOT EXISTS).
MIGRATIONS = {
    "samples": {"yaw": "REAL", "pitch": "REAL"},  # head pose at capture (vision.align.head_pose); NULL = unknown
    "people": {"profile_sample_id": "TEXT"},  # operator-chosen profile photo; NULL = most frontal sample
}

# Profile photo: the operator's choice if it still exists, else the most frontal sample (|yaw| + |pitch|; a person's
# natural pitch offset is shared by all their photos, while chin-up/down shots differ by ≥ 0.07), then the best
# quality. Samples with unknown pose sort after posed ones.
COVER_SQL = (
    "COALESCE((SELECT id FROM samples WHERE id = p.profile_sample_id AND person_id = p.id),"
    " (SELECT id FROM samples WHERE person_id = p.id"
    " ORDER BY yaw IS NULL, ABS(COALESCE(yaw, 0)) + ABS(COALESCE(pitch, 0)), sharpness * det_score DESC LIMIT 1))"
)


def utcnow() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class GalleryStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._conn.executescript(SCHEMA)
        self._migrate()
        self.version = 0  # bumped on every gallery change so the matcher index knows to rebuild

    def _migrate(self) -> None:
        with self._tx() as c:
            for table, cols in MIGRATIONS.items():
                have = {r["name"] for r in c.execute(f"PRAGMA table_info({table})")}
                for col, typ in cols.items():
                    if col not in have:
                        c.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typ}")

    def close(self) -> None:
        self._conn.close()

    @contextmanager
    def _tx(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            try:
                yield self._conn
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise

    def _touch(self) -> None:
        self.version += 1

    # ------------------------------------------------------------------ people
    def create_person(
        self, name: str, employee_id: str | None = None, department: str | None = None, notes: str | None = None
    ) -> dict[str, Any]:
        pid, now = uuid.uuid4().hex, utcnow()
        with self._tx() as c:
            c.execute(
                "INSERT INTO people (id, name, employee_id, department, notes, active, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, 1, ?, ?)",
                (pid, name.strip(), (employee_id or None), department, notes, now, now),
            )
        self._touch()
        return self.get_person(pid)  # type: ignore[return-value]

    def update_person(self, pid: str, **fields: Any) -> dict[str, Any] | None:
        allowed = {"name", "employee_id", "department", "notes", "active", "profile_sample_id"}
        sets = {k: v for k, v in fields.items() if k in allowed}
        if sets:
            if "active" in sets:
                sets["active"] = int(bool(sets["active"]))
            cols = ", ".join(f"{k} = ?" for k in sets)
            with self._tx() as c:
                c.execute(f"UPDATE people SET {cols}, updated_at = ? WHERE id = ?", (*sets.values(), utcnow(), pid))
            self._touch()
        return self.get_person(pid)

    def delete_person(self, pid: str) -> bool:
        with self._tx() as c:
            cur = c.execute("DELETE FROM people WHERE id = ?", (pid,))
        self._touch()
        return cur.rowcount > 0

    def get_person(self, pid: str) -> dict[str, Any] | None:
        rows = self.list_people(person_id=pid)
        return rows[0] if rows else None

    def list_people(self, query: str | None = None, person_id: str | None = None) -> list[dict[str, Any]]:
        sql = (
            "SELECT p.*, COUNT(s.id) AS sample_count,"
            f" {COVER_SQL} AS cover_sample_id"
            " FROM people p LEFT JOIN samples s ON s.person_id = p.id"
        )
        where, args = [], []
        if person_id:
            where.append("p.id = ?")
            args.append(person_id)
        if query:
            where.append("(p.name LIKE ? OR p.employee_id LIKE ? OR p.department LIKE ?)")
            args += [f"%{query}%"] * 3
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " GROUP BY p.id ORDER BY p.name COLLATE NOCASE"
        with self._lock:
            rows = self._conn.execute(sql, args).fetchall()
        return [dict(r) | {"active": bool(r["active"])} for r in rows]

    # ------------------------------------------------------------------ samples
    def add_sample(
        self,
        person_id: str,
        det_score: float,
        sharpness: float,
        face_px: float,
        embeddings: dict[str, np.ndarray],
        thumb: bytes | None,
        pose: tuple[float, float] | None = None,
    ) -> str:
        sid = uuid.uuid4().hex
        yaw, pitch = pose if pose else (None, None)
        with self._tx() as c:
            c.execute(
                "INSERT INTO samples (id, person_id, det_score, sharpness, face_px, thumb, created_at, yaw, pitch)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (sid, person_id, det_score, sharpness, face_px, thumb, utcnow(), yaw, pitch),
            )
            c.executemany(
                "INSERT INTO embeddings (sample_id, model, dim, vector) VALUES (?, ?, ?, ?)",
                [(sid, m, int(v.shape[0]), v.astype(np.float32).tobytes()) for m, v in embeddings.items()],
            )
        self._touch()
        return sid

    def set_embedding(self, sample_id: str, model: str, vector: np.ndarray) -> None:
        with self._tx() as c:
            c.execute(
                "INSERT OR REPLACE INTO embeddings (sample_id, model, dim, vector) VALUES (?, ?, ?, ?)",
                (sample_id, model, int(vector.shape[0]), vector.astype(np.float32).tobytes()),
            )
        self._touch()

    def list_samples(self, person_id: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT s.id, s.person_id, s.det_score, s.sharpness, s.face_px, s.created_at, s.yaw, s.pitch,"
                " s.thumb IS NOT NULL AS has_thumb, GROUP_CONCAT(e.model) AS models"
                " FROM samples s LEFT JOIN embeddings e ON e.sample_id = s.id"
                " WHERE s.person_id = ? GROUP BY s.id ORDER BY s.created_at",
                (person_id,),
            ).fetchall()
        return [dict(r) | {"has_thumb": bool(r["has_thumb"]), "models": (r["models"] or "").split(",")} for r in rows]

    def count_samples(self, person_id: str) -> int:
        with self._lock:
            row = self._conn.execute("SELECT COUNT(*) FROM samples WHERE person_id = ?", (person_id,)).fetchone()
        return int(row[0])

    def get_thumb(self, sample_id: str) -> bytes | None:
        with self._lock:
            row = self._conn.execute("SELECT thumb FROM samples WHERE id = ?", (sample_id,)).fetchone()
        return row["thumb"] if row else None

    def set_pose(self, sample_id: str, yaw: float, pitch: float) -> None:
        with self._tx() as c:
            c.execute("UPDATE samples SET yaw = ?, pitch = ? WHERE id = ?", (yaw, pitch, sample_id))

    def iter_unposed_thumbs(self) -> list[tuple[str, bytes]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, thumb FROM samples WHERE yaw IS NULL AND thumb IS NOT NULL"
            ).fetchall()
        return [(r["id"], r["thumb"]) for r in rows]

    def iter_thumbs(self) -> Iterator[tuple[str, bytes]]:
        with self._lock:
            rows = self._conn.execute("SELECT id, thumb FROM samples WHERE thumb IS NOT NULL").fetchall()
        yield from ((r["id"], r["thumb"]) for r in rows)

    def delete_sample(self, sample_id: str, person_id: str | None = None) -> bool:
        sql, args = "DELETE FROM samples WHERE id = ?", [sample_id]
        if person_id:
            sql += " AND person_id = ?"
            args.append(person_id)
        with self._tx() as c:
            cur = c.execute(sql, args)
        self._touch()
        return cur.rowcount > 0

    def load_embeddings(self, model: str, active_only: bool = True) -> tuple[np.ndarray, list[str]]:
        """Return ``(N, D)`` matrix and the person id of each row for one model."""
        sql = (
            "SELECT s.person_id, e.vector, e.dim FROM embeddings e"
            " JOIN samples s ON s.id = e.sample_id JOIN people p ON p.id = s.person_id WHERE e.model = ?"
        )
        if active_only:
            sql += " AND p.active = 1"
        with self._lock:
            rows = self._conn.execute(sql, (model,)).fetchall()
        if not rows:
            return np.zeros((0, 0), dtype=np.float32), []
        mat = np.stack([np.frombuffer(r["vector"], dtype=np.float32, count=r["dim"]) for r in rows])
        return mat, [r["person_id"] for r in rows]

    # ------------------------------------------------------------------ events
    def add_event(
        self,
        person_id: str | None,
        name: str | None,
        status: str,
        score: float | None,
        mode: str,
        source: str,
        thumb: bytes | None = None,
    ) -> int:
        with self._tx() as c:
            cur = c.execute(
                "INSERT INTO events (ts, person_id, name, status, score, mode, source, thumb)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (utcnow(), person_id, name, status, score, mode, source, thumb),
            )
        return int(cur.lastrowid or 0)

    def list_events(
        self, limit: int = 50, status: str | None = None, person_id: str | None = None, since: str | None = None
    ) -> list[dict[str, Any]]:
        sql = "SELECT id, ts, person_id, name, status, score, mode, source, thumb IS NOT NULL AS has_thumb FROM events"
        where, args = [], []
        if status:
            where.append("status = ?")
            args.append(status)
        if person_id:
            where.append("person_id = ?")
            args.append(person_id)
        if since:
            where.append("ts >= ?")
            args.append(since)
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY id DESC LIMIT ?"
        args.append(limit)
        with self._lock:
            rows = self._conn.execute(sql, args).fetchall()
        return [dict(r) | {"has_thumb": bool(r["has_thumb"])} for r in rows]

    def get_event_thumb(self, event_id: int) -> bytes | None:
        with self._lock:
            row = self._conn.execute("SELECT thumb FROM events WHERE id = ?", (event_id,)).fetchone()
        return row["thumb"] if row else None

    def purge_events(self, older_than_days: int) -> int:
        cutoff = (datetime.now(UTC) - timedelta(days=older_than_days)).isoformat(timespec="seconds")
        with self._tx() as c:
            cur = c.execute("DELETE FROM events WHERE ts < ?", (cutoff,))
        return cur.rowcount

    # ------------------------------------------------------------------ stats
    def stats(self) -> dict[str, Any]:
        today = datetime.now(UTC).date().isoformat()
        with self._lock:
            c = self._conn
            people = c.execute("SELECT COUNT(*), COALESCE(SUM(active), 0) FROM people").fetchone()
            samples = c.execute("SELECT COUNT(*) FROM samples").fetchone()[0]
            no_samples = c.execute(
                "SELECT COUNT(*) FROM people p WHERE NOT EXISTS (SELECT 1 FROM samples s WHERE s.person_id = p.id)"
            ).fetchone()[0]
            ev = c.execute("SELECT status, COUNT(*) FROM events WHERE ts >= ? GROUP BY status", (today,)).fetchall()
            unique_today = c.execute(
                "SELECT COUNT(DISTINCT person_id) FROM events WHERE ts >= ? AND status = 'match'", (today,)
            ).fetchone()[0]
            hourly = c.execute(
                "SELECT substr(ts, 12, 2) AS hour, COUNT(*) FROM events WHERE ts >= ? GROUP BY hour", (today,)
            ).fetchall()
        events_today = {r[0]: r[1] for r in ev}
        return {
            "people": people[0],
            "active_people": people[1],
            "samples": samples,
            "people_without_samples": no_samples,
            "events_today": events_today,
            "recognised_today": unique_today,
            "hourly_today": {int(h): n for h, n in hourly},
        }
