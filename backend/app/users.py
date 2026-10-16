"""Manage command-center users from the terminal.

  cd backend
  ../.venv/bin/python -m app.users list
  ../.venv/bin/python -m app.users add  <username> <ANALYST|IO|SUPERVISOR> "<Full name>" ["<Designation>"]
  ../.venv/bin/python -m app.users password <username>
  ../.venv/bin/python -m app.users disable <username>
"""
import getpass
import sys

from . import audit
from .db import SessionLocal, User, init_db
from .security import hash_password, password_problem

CLI = {"id": None, "username": "terminal", "role": "SYSTEM"}


def _ask_password() -> str:
    while True:
        pw = getpass.getpass("New password: ")
        if password_problem(pw):
            print(password_problem(pw))
            continue
        if getpass.getpass("Repeat: ") != pw:
            print("Passwords don't match")
            continue
        return pw


def main(argv):
    init_db()
    if not argv or argv[0] not in ("list", "add", "password", "disable", "enable"):
        print(__doc__)
        return 1
    cmd, args = argv[0], argv[1:]
    with SessionLocal() as s:
        if cmd == "list":
            for u in s.query(User).order_by(User.id):
                print(f"{u.username:16} {u.role:11} {'active' if u.active else 'disabled':9} {u.name} ({u.designation})")
            return 0
        if not args:
            print(__doc__)
            return 1
        uname = args[0].lower()
        u = s.query(User).filter_by(username=uname).first()
        if cmd == "add":
            if u:
                print("That username exists")
                return 1
            if len(args) < 3 or args[1] not in ("ANALYST", "IO", "SUPERVISOR"):
                print(__doc__)
                return 1
            s.add(User(username=uname, role=args[1], name=args[2], designation=args[3] if len(args) > 3 else "",
                       password_hash=hash_password(_ask_password())))
            s.commit()
            audit.log(CLI, "user.created", detail={"username": uname, "role": args[1]})
            print("Added", uname)
            return 0
        if not u:
            print("No such user")
            return 1
        if cmd == "password":
            u.password_hash = hash_password(_ask_password())
            u.session_version = (u.session_version or 1) + 1
            audit_action = "user.password_reset"
        else:
            u.active = cmd == "enable"
            u.session_version = (u.session_version or 1) + 1
            audit_action = f"user.{cmd}d"
        s.commit()
        audit.log(CLI, audit_action, detail={"user": uname})
        print("Done")
        return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
