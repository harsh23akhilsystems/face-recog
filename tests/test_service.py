"""Enrollment rules, open-set identification, matching modes, events and runtime settings."""

from __future__ import annotations

import json

import numpy as np

from facegate.evaluation import roc_metrics
from facegate.gallery.matcher import Matcher
from tests.conftest import face_image, prototype


def _enroll(service, name, identity, n=3):
    p = service.store.create_person(name, employee_id=f"E{identity}")
    res = service.enroll(p["id"], [(f"{i}.jpg", face_image(identity, i + 1)) for i in range(n)])
    assert all(r.accepted for r in res), [r.reason for r in res]
    return p


def test_enroll_and_identify(service):
    alice = _enroll(service, "Alice", 1)
    _enroll(service, "Bob", 2)
    out = service.recognize(face_image(1, 9), log_events=False)
    assert out["mode"] == "fusion"
    face = out["faces"][0]
    assert face["status"] == "match"
    assert face["person"]["id"] == alice["id"]
    assert set(face["per_model"]) == {"arcface", "adaface"}


def test_unknown_face_is_not_matched(service):
    _enroll(service, "Alice", 1)
    face = service.recognize(face_image(50, 1), log_events=False)["faces"][0]
    assert face["status"] == "unknown"
    assert face["person"] is None


def test_enroll_rejects_no_face_and_duplicates(service):
    _enroll(service, "Alice", 1)
    bob = service.store.create_person("Bob")
    res = service.enroll(bob["id"], [("empty.jpg", face_image(0)), ("alice.jpg", face_image(1, 4))])
    assert [r.accepted for r in res] == [False, False]
    assert "No face" in res[0].reason
    assert "Alice" in res[1].reason


def test_enroll_warns_on_multiple_faces_and_enforces_limit(service):
    p = service.store.create_person("Carol")
    res = service.enroll(p["id"], [("group.jpg", face_image(3, 1, faces=2))])
    assert res[0].accepted and res[0].warnings
    res = service.enroll(p["id"], [(f"{i}.jpg", face_image(3, i + 2)) for i in range(6)])
    assert sum(r.accepted for r in res) == 4  # limit is 5 in the test config
    assert "Limit" in res[-1].reason


def test_inactive_people_are_not_matched(service):
    alice = _enroll(service, "Alice", 1)
    service.store.update_person(alice["id"], active=False)
    assert service.recognize(face_image(1, 9), log_events=False)["faces"][0]["status"] == "unknown"


def test_modes_fall_back_when_model_missing(service):
    m = service.matcher
    assert m.effective_mode(["arcface"], "fusion") == "arcface"
    assert m.effective_mode(["arcface"], "adaface") == "arcface"
    assert m.effective_mode(["arcface", "adaface"], "strict") == "strict"


def test_strict_mode_requires_agreement(service):
    alice = _enroll(service, "Alice", 1)
    bob = _enroll(service, "Bob", 2)
    # ArcFace says Alice, AdaFace says Bob → strict must refuse, fusion picks one of them.
    emb = {"arcface": prototype("arcface", 1), "adaface": prototype("adaface", 2)}
    strict = service.matcher.identify(emb, "strict")
    assert strict.status != "match"
    assert service.matcher.identify(emb, "arcface").person_id == alice["id"]
    assert service.matcher.identify(emb, "adaface").person_id == bob["id"]


def test_margin_marks_ambiguous_as_uncertain(service):
    service.settings.matching.margin = 0.2  # generous margin so template noise cannot decide the outcome
    _enroll(service, "Alice", 1)
    _enroll(service, "Alice Twin", 2)
    mix = {m: (prototype(m, 1) + prototype(m, 2)) / np.sqrt(2) for m in ("arcface", "adaface")}
    assert service.matcher.identify(mix, "fusion").status == "uncertain"


def test_matcher_mean_aggregate(service, settings):
    _enroll(service, "Alice", 1)
    settings.matching.aggregate = "mean"
    m = Matcher(service.store, {"arcface": 0.3}, settings.matching)
    scores = m.person_scores("arcface", prototype("arcface", 1))
    assert 0.5 < next(iter(scores.values())) <= 1.0


def test_event_cooldown(service):
    _enroll(service, "Alice", 1)
    for _ in range(3):
        service.recognize(face_image(1, 9), source="camera")
    events = service.store.list_events()
    assert len(events) == 1 and events[0]["status"] == "match" and events[0]["name"] == "Alice"
    assert service.store.stats()["recognised_today"] == 1


def test_verify(service):
    same = service.verify(face_image(1, 1), face_image(1, 2))
    diff = service.verify(face_image(1, 1), face_image(2, 1))
    assert same["match"] and not diff["match"]
    assert same["fused_score"] > diff["fused_score"]


def test_runtime_settings_persist(service, settings):
    out = service.update_runtime_settings({"mode": "strict", "thresholds": {"arcface": 0.42}, "cooldown_seconds": 5})
    assert out["mode"] == "strict" and out["thresholds"]["arcface"] == 0.42
    saved = json.loads(settings.runtime_settings_path.read_text())
    assert saved["mode"] == "strict" and saved["cooldown_seconds"] == 5


def test_deleting_person_cascades(service):
    alice = _enroll(service, "Alice", 1)
    assert service.store.delete_person(alice["id"])
    mat, owners = service.store.load_embeddings("arcface")
    assert owners == []


def test_roc_metrics_separable():
    rng = np.random.default_rng(0)
    scores = np.concatenate([rng.normal(0.7, 0.05, 200), rng.normal(0.0, 0.05, 5000)])
    same = np.concatenate([np.ones(200, bool), np.zeros(5000, bool)])
    r = roc_metrics(scores, same, target_far=1e-3)
    assert r["auc"] > 0.999 and r["eer"] < 0.01
    assert 0.1 < r["recommended"]["threshold"] < 0.6
