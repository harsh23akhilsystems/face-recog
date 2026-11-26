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


def test_detect_reports_quality_and_pose(client):
    r = client.post("/api/v1/detect", files={"image": ("q.png", jpg(face_image(1)), "image/png")}).json()
    face = r["faces"][0]
    assert set(face["pose"]) == {"yaw", "pitch"} and abs(face["pose"]["yaw"]) < 0.05
    assert face["sharpness"] >= 0 and face["face_sharpness"] >= 0 and len(face["landmarks"]) == 5


def test_enrollment_guide_matches_enroll_gates(client, settings):
    g = client.get("/api/v1/enrollment/guide").json()
    assert len(g["steps"]) >= 7 and g["steps"][0]["key"] == "front"
    assert g["min_face_px"] == settings.enrollment.min_face_px
    assert g["max_samples_per_person"] == settings.enrollment.max_samples_per_person
    assert all({"key", "prompt", "hint", "yaw", "pitch"} <= set(s) for s in g["steps"])
    assert set(g["phase_prompts"]) >= {s["hint"] for s in g["steps"]}
    assert g["remind_ms"] >= 1000 and g["best_window_ms"] >= 0
    for path in g["animations"].values():  # configured Lottie files must exist (console serves them from /assets)
        assert client.get(f"/assets/{path}").status_code == 200
    assert client.get("/assets/vendor/lottie/lottie_light.min.js").status_code == 200
    styles_js = client.get("/assets/js/guide-styles.js").text  # default style must exist in the console's STYLES
    assert f"id: '{g['guide_style']}'" in styles_js


def test_duplicate_check_names_existing_person(client):
    alice = client.post("/api/v1/people", json={"name": "Alice", "employee_id": "EMP-7"}).json()
    one = [("images", ("a.png", jpg(face_image(1, 1)), "image/png"))]
    client.post(f"/api/v1/people/{alice['id']}/samples", files=one)
    r = client.post("/api/v1/people", json={"name": "Again", "employee_id": "EMP-7"})
    assert r.status_code == 409 and "Alice" in r.json()["detail"]
    new = client.post("/api/v1/people", json={"name": "Alice again"}).json()
    r = client.post(
        f"/api/v1/people/{new['id']}/duplicate-check", files={"image": ("q.png", jpg(face_image(1, 2)), "image/png")}
    ).json()
    assert r["duplicate_of"]["name"] == "Alice" and r["duplicate_of"]["employee_id"] == "EMP-7"
    res = client.post(
        f"/api/v1/people/{new['id']}/samples", files=[("images", ("b.png", jpg(face_image(1, 3)), "image/png"))]
    ).json()
    assert res["accepted"] == 0 and res["results"][0]["duplicate_of"]["employee_id"] == "EMP-7"
    assert "EMP-7" in res["results"][0]["reason"]


def test_samples_check_is_a_dry_run(client, settings):
    pid = client.post("/api/v1/people", json={"name": "Dana"}).json()["id"]
    files = [("images", (f"{i}.png", jpg(face_image(4, i + 1)), "image/png")) for i in range(2)]
    files.insert(1, ("images", ("bad.txt", b"nope", "text/plain")))
    files.append(("images", ("none.png", jpg(face_image(0)), "image/png")))
    r = client.post(f"/api/v1/people/{pid}/samples/check", files=files).json()
    assert [x["accepted"] for x in r["results"]] == [True, False, True, False]  # upload order kept
    assert "decode" in r["results"][1]["reason"] and "No face" in r["results"][3]["reason"]
    assert client.get(f"/api/v1/people/{pid}").json()["samples"] == []  # nothing stored
    limit = settings.enrollment.max_samples_per_person
    many = [("images", (f"{i}.png", jpg(face_image(4, i + 1)), "image/png")) for i in range(limit + 2)]
    r = client.post(f"/api/v1/people/{pid}/samples/check", files=many).json()
    assert r["accepted"] == limit and "Limit" in r["results"][-1]["reason"]


def test_set_profile_photo(client):
    a = client.post("/api/v1/people", json={"name": "Gus"}).json()["id"]
    b = client.post("/api/v1/people", json={"name": "Hal"}).json()["id"]
    for pid, ident in ((a, 6), (b, 7)):
        photo = [("images", ("x.png", jpg(face_image(ident, 1)), "image/png"))]
        client.post(f"/api/v1/people/{pid}/samples", files=photo)
    sid_a = client.get(f"/api/v1/people/{a}").json()["samples"][0]["id"]
    sid_b = client.get(f"/api/v1/people/{b}").json()["samples"][0]["id"]
    assert client.patch(f"/api/v1/people/{a}", json={"profile_sample_id": sid_b}).status_code == 422
    r = client.patch(f"/api/v1/people/{a}", json={"profile_sample_id": sid_a}).json()
    assert r["cover_sample_id"] == sid_a
    assert client.patch(f"/api/v1/people/{a}", json={"profile_sample_id": None}).status_code == 200
