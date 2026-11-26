"""Sign-in: route protection, password + face sign-in, lockout, liveness, sessions and user administration."""

from __future__ import annotations

import stat

import cv2
import pytest
from fastapi.testclient import TestClient

from facegate.api.main import create_app
from facegate.auth import hash_password, verify_password
from tests.conftest import TEST_PASSWORD, face_image, signed_in_client


def png(img) -> bytes:
    return cv2.imencode(".png", img)[1].tobytes()


def image(identity: int, variant: int = 0, faces: int = 1) -> dict:
    return {"image": ("f.png", png(face_image(identity, variant, faces)), "image/png")}


@pytest.fixture()
def anon(service):
    with TestClient(create_app(service), follow_redirects=False) as c:
        yield c


def enroll_linked(c: TestClient, identity: int, username: str) -> str:
    """Gallery person with samples for ``identity`` and a user account linked to them."""
    pid = c.app.state.service.store.create_person(f"Person {identity}")["id"]
    c.app.state.service.enroll(pid, [(f"{i}.png", face_image(identity, i + 1)) for i in range(3)])
    c.app.state.auth.create_user(username, TEST_PASSWORD, display_name=f"User {identity}", person_id=pid)
    return pid


class FakeLiveness:
    def __init__(self, real: bool) -> None:
        self.real = real

    def score(self, img, bbox) -> dict:
        return {"score": 1.0 if self.real else -2.0, "real": self.real, "threshold": 0.0}


# ---------------------------------------------------------------------- protection
def test_signed_out_is_redirected_or_refused(anon):
    assert anon.get("/api/v1/people").status_code == 401
    assert anon.get("/api/v1/settings").status_code == 401
    assert anon.post("/api/v1/recognize", files=image(1)).status_code == 401
    r = anon.get("/")
    assert r.status_code == 303 and r.headers["location"] == "/login"
    assert anon.get("/login").status_code == 200
    assert anon.get("/assets/js/login.js").status_code == 200


def test_health_is_public_but_reduced(anon):
    h = anon.get("/api/v1/health").json()
    assert h["ready"] and h["signed_in"] is False
    assert "models" not in h and "people" not in h


def test_first_start_creates_admin_with_private_credentials(anon, settings):
    path = settings.data_dir / "initial_admin_credentials.txt"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    password = path.read_text().split("password: ")[1].strip()
    r = anon.post("/auth/login", json={"username": "admin", "password": password})
    assert r.status_code == 200 and r.json()["user"]["role"] == "admin"


def test_password_hashing():
    h = hash_password("s3cret-pass", 1000)
    assert verify_password("s3cret-pass", h) and not verify_password("wrong", h)
    assert not verify_password("x", "garbage")


# ---------------------------------------------------------------------- password sign-in
def test_password_login_session_and_logout(anon):
    anon.app.state.auth.create_user("alice", TEST_PASSWORD, "Alice A")
    bad = anon.post("/auth/login", json={"username": "alice", "password": "nope"})
    assert bad.status_code == 401 and bad.json()["detail"] == "Invalid username or password."
    unknown = anon.post("/auth/login", json={"username": "ghost", "password": "nope"})
    assert unknown.json()["detail"] == bad.json()["detail"]  # no account enumeration

    r = anon.post("/auth/login", json={"username": "ALICE", "password": TEST_PASSWORD})
    assert r.status_code == 200
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie
    me = anon.get("/auth/me").json()
    assert me["user"]["display_name"] == "Alice A" and me["method"] == "password"
    assert anon.get("/api/v1/people").status_code == 200
    assert anon.get("/").status_code == 200
    assert anon.get("/login").status_code == 303

    assert anon.post("/auth/logout").status_code == 200
    assert anon.get("/api/v1/people").status_code == 401
    events = [(e["method"], e["outcome"]) for e in anon.app.state.auth.events()]
    assert ("password", "failed") in events and ("password", "success") in events and ("logout", "success") in events


def test_password_lockout(anon):
    anon.app.state.auth.create_user("bob", TEST_PASSWORD)
    for _ in range(5):
        assert anon.post("/auth/login", json={"username": "bob", "password": "wrong"}).status_code == 401
    r = anon.post("/auth/login", json={"username": "bob", "password": TEST_PASSWORD})
    assert r.status_code == 429  # locked even with the right password


def test_password_change_ends_sessions(service):
    with signed_in_client(service, "carol") as c:
        auth = c.app.state.auth
        auth.update_user(auth.get_by_username("carol").id, password="another-pass-9")
        assert c.get("/api/v1/people").status_code == 401


# ---------------------------------------------------------------------- face sign-in
def test_quality_guidance(anon):
    q = anon.post("/auth/quality", files=image(1)).json()
    assert q["ok"] and q["faces_found"] == 1 and len(q["face"]["box"]) == 4
    none = anon.post("/auth/quality", files=image(0)).json()
    assert not none["ok"] and none["issues"] == ["no_face"] and "No face" in none["advice"][0]
    two = anon.post("/auth/quality", files=image(1, faces=2)).json()
    assert two["issues"][0] == "multiple_faces"


def test_face_login_flow(anon):
    assert anon.get("/auth/face/status").json() == {"available": True, "any_enrolled": False, "liveness": False}
    enroll_linked(anon, 1, "dave")
    assert anon.get("/auth/face/status").json()["any_enrolled"]

    r = anon.post("/auth/face", files=image(1, 9))
    assert r.status_code == 200, r.text
    assert r.json()["user"]["username"] == "dave" and r.json()["method"] == "face"
    assert anon.get("/auth/me").json()["method"] == "face"


def test_face_login_rejections(anon):
    enroll_linked(anon, 1, "erin")
    # someone not in the gallery
    assert anon.post("/auth/face", files=image(2, 1)).status_code == 401
    # enrolled in the gallery but with no linked account
    pid = anon.app.state.service.store.create_person("No Account")["id"]
    anon.app.state.service.enroll(pid, [("a.png", face_image(3, 1))])
    assert anon.post("/auth/face", files=image(3, 2)).status_code == 401
    # framing problem → guidance (422) with the face box for the overlay; neither counted nor logged
    r = anon.post("/auth/face", files=image(1, 1, faces=2))
    assert r.status_code == 422 and "More than one face" in r.json()["detail"]
    assert r.json()["quality"]["issues"][0] == "multiple_faces"
    outcomes = [e["outcome"] for e in anon.app.state.auth.events() if e["method"] == "face"]
    assert outcomes == ["failed", "failed"]
    assert anon.get("/api/v1/people").status_code == 401


def test_face_lockout_per_client(anon):
    enroll_linked(anon, 1, "frank")
    for _ in range(10):
        assert anon.post("/auth/face", files=image(2, 1)).status_code == 401
    assert anon.post("/auth/face", files=image(1, 1)).status_code == 429


def test_liveness_enforced(anon):
    enroll_linked(anon, 1, "gina")
    anon.app.state.service.pipeline.liveness = FakeLiveness(real=False)
    r = anon.post("/auth/face", files=image(1, 2))
    assert r.status_code == 401 and "Liveness" in r.json()["detail"]
    anon.app.state.service.pipeline.liveness = FakeLiveness(real=True)
    assert anon.post("/auth/face", files=image(1, 2)).status_code == 200


def test_face_login_unavailable_without_models(service):
    service.pipeline.recognizers.clear()
    with TestClient(create_app(service)) as c:
        assert c.get("/auth/face/status").json()["available"] is False
        assert c.post("/auth/face", files=image(1)).status_code == 503


def test_deleting_person_unlinks_account(anon):
    pid = enroll_linked(anon, 1, "hank")
    anon.app.state.service.store.delete_person(pid)
    user = anon.app.state.auth.get_by_username("hank")
    assert user is not None and user.person_id is None
    assert anon.post("/auth/face", files=image(1, 2)).status_code == 401


# ---------------------------------------------------------------------- user administration
def test_user_admin(service):
    with signed_in_client(service, "root") as c:
        pid = c.app.state.service.store.create_person("Ivy")["id"]
        r = c.post("/auth/users", json={"username": "ivy", "password": "ivy-password", "person_id": pid})
        assert r.status_code == 201 and r.json()["face_login"]
        uid = r.json()["id"]
        assert c.post("/auth/users", json={"username": "ivy", "password": "ivy-password"}).status_code == 422
        assert c.post("/auth/users", json={"username": "short", "password": "x"}).status_code == 422
        other = c.post("/auth/users", json={"username": "jo", "password": "jo-password", "person_id": pid})
        assert other.status_code == 422 and "already linked" in other.json()["detail"]

        assert c.patch(f"/auth/users/{uid}", json={"person_id": ""}).json()["face_login"] is False
        users = {u["username"]: u for u in c.get("/auth/users").json()}
        assert set(users) >= {"admin", "root", "ivy"}

        me = c.get("/auth/me").json()["user"]["id"]
        assert c.delete(f"/auth/users/{me}").status_code == 409
        assert c.delete(f"/auth/users/{uid}").status_code == 204
        assert c.post("/auth/login", json={"username": "ivy", "password": "ivy-password"}).status_code == 401
        assert c.get("/auth/events").status_code == 200


def test_staff_and_face_sessions_cannot_manage_users(service):
    with signed_in_client(service, "kim", role="staff") as c:
        assert c.get("/auth/users").status_code == 403
        assert c.get("/api/v1/people").status_code == 200  # but can use the console
        c.post("/auth/logout")
        enroll_linked(c, 1, "lee")
        c.app.state.auth.update_user(c.app.state.auth.get_by_username("lee").id, role="admin")
        assert c.post("/auth/face", files=image(1, 2)).status_code == 200
        r = c.get("/auth/users")
        assert r.status_code == 403 and "password" in r.json()["detail"]


def test_last_admin_cannot_be_demoted(service):
    with signed_in_client(service, "solo") as c:
        auth = c.app.state.auth
        auth.deactivate_user(auth.get_by_username("admin").id)  # leave "solo" as the only admin
        me = c.get("/auth/me").json()["user"]["id"]
        assert c.patch(f"/auth/users/{me}", json={"role": "staff"}).status_code == 409
