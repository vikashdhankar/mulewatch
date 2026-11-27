"""Create (or refresh) the top-level account for the Superintendent of Police.

The account gets the SUPERVISOR role, the highest role in this app: every page, user management,
the audit log, assignment of any case and override of any status.

Run it with the same data folder (MW_DATA_DIR) the server will use:

  ./run.sh add-sp                              # username "sp", asks for the password
  ./run.sh add-sp --username sp.meharda
  SP_PASSWORD='...' ./run.sh add-sp            # no prompt, for scripts

or from the backend folder: ../.venv/bin/python -m app.sp_admin [--username ...]

Running it again for an existing username resets that account's password, makes it active SUPERVISOR again
and signs out its old sessions.
"""
import argparse
import getpass
import os
import sys
from pathlib import Path

from . import audit
from .auth import ensure_demo_users
from .db import SessionLocal, User, engine, init_db
from .security import hash_password, password_problem

CLI = {"id": None, "username": "terminal", "role": "SYSTEM"}
PASSWORD_ENV = "SP_PASSWORD"


def ask_password() -> str:
    while True:
        pw = getpass.getpass("Password for the SP account: ")
        if password_problem(pw):
            print(password_problem(pw))
            continue
        if getpass.getpass("Repeat: ") != pw:
            print("Passwords don't match")
            continue
        return pw


def database_label() -> str:
    """The database file for SQLite, otherwise the URL with its password hidden."""
    url = engine.url
    if url.get_backend_name() == "sqlite" and url.database:
        return str(Path(url.database).resolve())
    return url.render_as_string(hide_password=True)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="./run.sh add-sp", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--username", default="sp")
    ap.add_argument("--name", default="Sh. Sumeet Meharda")
    ap.add_argument("--designation", default="Superintendent of Police")
    ap.add_argument("--station", default="Police Headquarters, Jaipur")
    a = ap.parse_args(argv)
    uname = a.username.strip().lower()
    if not uname.replace("_", "").replace(".", "").isalnum():
        print("Username: letters, numbers, dot or underscore only")
        return 1

    env_pw = os.environ.get(PASSWORD_ENV)
    if env_pw is not None and password_problem(env_pw):
        print(f"{PASSWORD_ENV}: {password_problem(env_pw)} Nothing was changed.", file=sys.stderr)
        return 1

    init_db()
    ensure_demo_users()          # keep the analyst / io / sho demo accounts on a fresh database
    print(f"Database: {database_label()}")
    if env_pw is not None:
        pw = env_pw
        print(f"Password: taken from {PASSWORD_ENV}")
    else:
        try:
            pw = ask_password()
        except (KeyboardInterrupt, EOFError):
            print("\nCancelled. Nothing was changed.")
            return 1

    with SessionLocal() as s:
        u = s.query(User).filter_by(username=uname).first()
        created = u is None
        if created:
            u = User(username=uname)
            s.add(u)
        u.name, u.designation, u.police_station = a.name, a.designation, a.station
        u.role, u.active, u.must_change_password = "SUPERVISOR", True, False
        u.password_hash = hash_password(pw)
        u.session_version = (u.session_version or 0) + 1      # signs out any old session of this account
        s.commit()

    audit.log(CLI, "user.created" if created else "user.updated",
              detail={"username": uname, "role": "SUPERVISOR", "by": "app.sp_admin"})
    print(f"{'Created' if created else 'Updated'} '{uname}' ({a.name}, {a.designation}) with SUPERVISOR (top) access.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
