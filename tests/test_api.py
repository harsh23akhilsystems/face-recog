"""HTTP contract tests against the FastAPI app with an injected fake service."""

from __future__ import annotations

import cv2
import pytest
from fastapi.testclient import TestClient

from facegate.api.main import create_app
from tests.conftest import face_image


def jpg(img) -> bytes:
    # PNG keeps the identity-encoding pixel exact (JPEG would blur it).
    return cv2.imencode(".png", img)[1].tobytes()


@pytest.fixture()
def client(service):
    with TestClient(create_app(service)) as c:
        yield c


def test_health_and_console(client):
    h = client.get("/api/v1/health").json()
    assert h["ready"] and h["status"] == "ok"
    assert {m["name"] for m in h["models"]} == {"scrfd", "arcface", "adaface"}
    assert client.get("/").status_code == 200


def test_people_crud_enroll_recognize(client):
    r = client.post("/api/v1/people", json={"name": "Alice", "employee_id": "E1", "department": "Ops"})
    assert r.status_code == 201
    pid = r.json()["id"]
    assert client.post("/api/v1/people", json={"name": "Dup", "employee_id": "E1"}).status_code == 409

    files = [("images", (f"{i}.png", jpg(face_image(1, i + 1)), "image/png")) for i in range(3)]
    files.append(("images", ("bad.txt", b"not an image", "text/plain")))
    r = client.post(f"/api/v1/people/{pid}/samples", files=files).json()
    assert r["accepted"] == 3 and r["person"]["sample_count"] == 3
    assert any("decode" in (x["reason"] or "") for x in r["results"])

    detail = client.get(f"/api/v1/people/{pid}").json()
    sid = detail["samples"][0]["id"]
    thumb = client.get(f"/api/v1/samples/{sid}/thumb")
    assert thumb.status_code == 200 and thumb.headers["content-type"] == "image/jpeg"

    r = client.post(
        "/api/v1/recognize", files={"image": ("q.png", jpg(face_image(1, 7)), "image/png")}, data={"source": "camera"}
    ).json()
    assert r["faces"][0]["status"] == "match" and r["faces"][0]["person"]["name"] == "Alice"
    events = client.get("/api/v1/events").json()
    assert events[0]["name"] == "Alice"
    assert client.get(f"/api/v1/events/{events[0]['id']}/thumb").status_code == 200

    assert client.patch(f"/api/v1/people/{pid}", json={"department": "Finance"}).json()["department"] == "Finance"
    assert client.delete(f"/api/v1/people/{pid}/samples/{sid}").status_code == 204
    assert client.delete(f"/api/v1/people/{pid}").status_code == 204
    assert client.get(f"/api/v1/people/{pid}").status_code == 404


def test_verify_and_errors(client):
    ok = client.post(
        "/api/v1/verify",
        files={
            "image_a": ("a.png", jpg(face_image(1, 1)), "image/png"),
            "image_b": ("b.png", jpg(face_image(1, 2)), "image/png"),
        },
    )
    assert ok.status_code == 200 and ok.json()["match"]
    noface = client.post(
        "/api/v1/verify",
        files={
            "image_a": ("a.png", jpg(face_image(0)), "image/png"),
            "image_b": ("b.png", jpg(face_image(1, 2)), "image/png"),
        },
    )
    assert noface.status_code == 422 and "No face" in noface.json()["detail"]
    bad_mode = client.post(
        "/api/v1/recognize", files={"image": ("q.png", jpg(face_image(1)), "image/png")}, data={"mode": "nope"}
    )
    assert bad_mode.status_code == 422


def test_settings_roundtrip(client):
    s = client.put("/api/v1/settings", json={"mode": "arcface", "margin": 0.1}).json()
    assert s["mode"] == "arcface" and s["margin"] == 0.1
    assert client.put("/api/v1/settings", json={"mode": "bogus"}).status_code == 422
    assert client.get("/api/v1/stats").json()["people"] == 0


def test_not_ready_returns_503(service):
    service.pipeline.recognizers.clear()
    with TestClient(create_app(service)) as c:
        r = c.post("/api/v1/recognize", files={"image": ("q.png", jpg(face_image(1)), "image/png")})
        assert r.status_code == 503
