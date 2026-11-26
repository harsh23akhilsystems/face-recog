"""Command-line interface: ``facegate <command>`` (or ``python -m facegate.cli``).

Bulk operations (enrolling a whole staff folder, calibrating thresholds) are much faster from the
shell than from the browser, and they are scriptable for HR onboarding jobs.
"""

from __future__ import annotations

import argparse
import getpass
import json
import logging
import sys
from pathlib import Path

import cv2

from facegate.auth import AuthService
from facegate.config import get_settings
from facegate.evaluation import IMAGE_EXT, evaluate
from facegate.gallery.store import GalleryStore
from facegate.service import FaceService
from facegate.vision.pipeline import FacePipeline


def _service() -> FaceService:
    svc = FaceService.from_settings(get_settings())
    if not svc.pipeline.ready:
        for s in svc.pipeline.status():
            if s.enabled and not s.loaded:
                print(f"  ✗ {s.name}: {s.error}", file=sys.stderr)
        raise SystemExit("Models not ready — run `make models` (and export AdaFace) first.")
    return svc


def _read(path: Path):
    img = cv2.imread(str(path))
    if img is None:
        raise SystemExit(f"Cannot read image: {path}")
    return img


def cmd_status(_: argparse.Namespace) -> None:
    svc = FaceService.from_settings(get_settings())
    print(json.dumps(svc.health(), indent=2))


def cmd_enroll_dir(args: argparse.Namespace) -> None:
    """Folder layout: root/<Person Name>[__EMPID]/<images>."""
    svc = _service()
    existing = {p["name"]: p for p in svc.store.list_people()}
    for person_dir in sorted(p for p in args.root.iterdir() if p.is_dir()):
        name, _, emp = person_dir.name.partition("__")
        person = existing.get(name) or svc.store.create_person(
            name, employee_id=emp or None, department=args.department
        )
        images = [(p.name, _read(p)) for p in sorted(person_dir.iterdir()) if p.suffix.lower() in IMAGE_EXT]
        results = svc.enroll(person["id"], images)
        ok = sum(r.accepted for r in results)
        print(f"{name:<30} {ok}/{len(results)} accepted")
        for r in results:
            if not r.accepted:
                print(f"    ✗ {r.filename}: {r.reason}")


def cmd_identify(args: argparse.Namespace) -> None:
    svc = _service()
    res = svc.recognize(_read(args.image), args.mode, source="cli", log_events=False)
    for f in res["faces"]:
        who = f["person"]["name"] if f["person"] else "—"
        print(f"{f['status']:<10} {who:<30} score={f['score']:.3f} per_model={f['per_model']} bbox={f['bbox']}")
    if not res["faces"]:
        print("No faces found")


def cmd_verify(args: argparse.Namespace) -> None:
    svc = _service()
    print(json.dumps(svc.verify(_read(args.a), _read(args.b)), indent=2))


def cmd_evaluate(args: argparse.Namespace) -> None:
    pipeline = FacePipeline.from_settings(get_settings())
    if not pipeline.ready:
        raise SystemExit("Models not ready")
    report = evaluate(pipeline, args.root, args.target_far)
    text = json.dumps(report, indent=2)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text)
        print(f"Report written to {args.out}", file=sys.stderr)
    print(text)


def cmd_reembed(_: argparse.Namespace) -> None:
    print(_service().reembed())


# ---------------------------------------------------------------------- users
def _auth() -> AuthService:
    """Account management needs only the database, not the ONNX models."""
    settings = get_settings()
    return AuthService(FaceService(settings, FacePipeline(None, {}, []), GalleryStore(settings.database_path)))


def _password(args: argparse.Namespace) -> str:
    if args.password:
        return args.password
    pw = getpass.getpass("Password: ")
    if pw != getpass.getpass("Repeat password: "):
        raise SystemExit("Passwords do not match")
    return pw


def _person_id(auth: AuthService, args: argparse.Namespace) -> str | None:
    """Resolve --person-id or --employee-id to a gallery person id ("" = unlink)."""
    if getattr(args, "unlink", False):
        return ""
    if args.employee_id:
        match = [p for p in auth.store.list_people(query=args.employee_id) if p["employee_id"] == args.employee_id]
        if not match:
            raise SystemExit(f"No gallery person with employee ID {args.employee_id!r}")
        return match[0]["id"]
    return args.person_id


def _user_or_exit(auth: AuthService, username: str):
    user = auth.get_by_username(username)
    if user is None:
        raise SystemExit(f"No active user {username!r}")
    return user


def cmd_user(args: argparse.Namespace) -> None:
    auth = _auth()
    try:
        if args.action == "list":
            for u in auth.list_users():
                face = f"face → {u['person_name']}" if u["person_id"] else "password only"
                print(f"{u['username']:<20} {u['role']:<6} {u['display_name']:<28} {face}")
        elif args.action == "add":
            u = auth.create_user(args.username, _password(args), args.name, args.role, _person_id(auth, args))
            print(f"Created {u.username} ({u.role})" + (" with face sign-in" if u.person_id else ""))
        elif args.action == "link":
            u = auth.update_user(_user_or_exit(auth, args.username).id, person_id=_person_id(auth, args) or "")
            print(f"{u.username}: " + ("face sign-in linked" if u.person_id else "face sign-in removed"))
        elif args.action == "passwd":
            auth.update_user(_user_or_exit(auth, args.username).id, password=_password(args))
            print(f"Password changed for {args.username}; their sessions were ended")
        elif args.action == "remove":
            user = _user_or_exit(auth, args.username)
            if user.is_admin and auth.active_admins() <= 1:
                raise SystemExit("Refusing to remove the last administrator")
            auth.deactivate_user(user.id)
            print(f"Removed {args.username}")
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    finally:
        auth.store.close()


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    ap = argparse.ArgumentParser(prog="facegate", description="FaceGate face recognition CLI")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("status", help="show model and gallery status").set_defaults(func=cmd_status)

    p = sub.add_parser("enroll-dir", help="bulk-enroll root/<Name>[__EMPID]/*.jpg")
    p.add_argument("root", type=Path)
    p.add_argument("--department")
    p.set_defaults(func=cmd_enroll_dir)

    p = sub.add_parser("identify", help="identify every face in an image")
    p.add_argument("image", type=Path)
    p.add_argument("--mode", choices=["arcface", "adaface", "fusion", "strict"])
    p.set_defaults(func=cmd_identify)

    p = sub.add_parser("verify", help="1:1 compare the largest face in two images")
    p.add_argument("a", type=Path)
    p.add_argument("b", type=Path)
    p.set_defaults(func=cmd_verify)

    p = sub.add_parser("evaluate", help="calibrate thresholds on a labelled folder root/<person>/*.jpg")
    p.add_argument("root", type=Path)
    p.add_argument("--target-far", type=float, default=1e-3)
    p.add_argument("--out", type=Path, default=Path("reports/evaluation.json"))
    p.set_defaults(func=cmd_evaluate)

    sub.add_parser("reembed", help="recompute embeddings from stored thumbnails").set_defaults(func=cmd_reembed)

    p = sub.add_parser("user", help="manage console sign-in accounts")
    us = p.add_subparsers(dest="action", required=True)
    us.add_parser("list", help="list active users").set_defaults(func=cmd_user)
    for action, text in (("add", "create a user"), ("link", "link/unlink a user to a gallery person for face sign-in")):
        q = us.add_parser(action, help=text)
        q.add_argument("username")
        who = q.add_mutually_exclusive_group(required=action == "link")
        who.add_argument("--person-id", help="gallery person id (People page / API)")
        who.add_argument("--employee-id", help="gallery person's employee ID")
        if action == "link":
            who.add_argument("--unlink", action="store_true", help="remove face sign-in")
        else:
            q.add_argument("--name", help="display name")
            q.add_argument("--role", choices=["admin", "staff"], default="staff")
            q.add_argument("--password", help="omit to be prompted (keeps it out of shell history)")
        q.set_defaults(func=cmd_user)
    q = us.add_parser("passwd", help="set a new password")
    q.add_argument("username")
    q.add_argument("--password", help="omit to be prompted")
    q.set_defaults(func=cmd_user)
    q = us.add_parser("remove", help="deactivate a user")
    q.add_argument("username")
    q.set_defaults(func=cmd_user)

    args = ap.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
