"""SP / Super Admin account: app.sp_admin (`./run.sh add-sp`), the old create_sp_admin.py, and signing in as sp."""
import os
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("MW_DATA_DIR", tempfile.mkdtemp())
os.environ["MW_SCREENSHOTS"] = "0"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402

from app import sp_admin  # noqa: E402
from app.db import SessionLocal, User  # noqa: E402
from app.main import app  # noqa: E402

BACKEND = Path(__file__).resolve().parent.parent
DATA_ENV, DEMO_ENV, DB_FILE = "MW_DATA_DIR", "MW_DEMO_USERS", "mulewatch.db"
PW1, PW2, PW3 = "Test@1234", "Second#5678", "Third$9012"      # test-only passwords


def run_cli(data_dir: Path, password: str | None, *args, script=("-m", "app.sp_admin")):
    """Run the command in a fresh process on its own data folder (an empty database)."""
    env = {k: v for k, v in os.environ.items() if k not in ("DATABASE_URL", "SP_PASSWORD")}
    env.update({DATA_ENV: str(data_dir), DEMO_ENV: "1"})
    if password is not None:
        env["SP_PASSWORD"] = password
    return subprocess.run([sys.executable, *script, *args], cwd=BACKEND, env=env, capture_output=True,
                          text=True, timeout=180, stdin=subprocess.DEVNULL)


def users_in(db: Path) -> dict:
    with sqlite3.connect(db) as c:
        return {r[0]: r[1:] for r in c.execute(
            "SELECT username, role, active, must_change_password, designation FROM users")}


def make_sp(monkeypatch, password: str, username: str = "sp") -> int:
    monkeypatch.setenv("SP_PASSWORD", password)
    return sp_admin.main(["--username", username])


def login(password: str, username: str = "sp"):
    c = TestClient(app)
    return c, c.post("/api/auth/login", json={"username": username, "password": password})


def test_creates_sp_on_empty_db_and_keeps_demo_users(tmp_path):
    r = run_cli(tmp_path, PW1)
    out = r.stdout + r.stderr
    assert r.returncode == 0, out
    db = (tmp_path / DB_FILE).resolve()
    assert f"Database: {db}" in r.stdout                 # says which database it wrote to
    assert PW1 not in out                                # never prints the password
    users = users_in(db)
    assert users["sp"] == ("SUPERVISOR", 1, 0, "Superintendent of Police")
    assert {u: v[0] for u, v in users.items() if u != "sp"} == {"analyst": "ANALYST", "io": "IO", "sho": "SUPERVISOR"}


def test_old_create_sp_admin_command_still_works(tmp_path):
    r = run_cli(tmp_path, PW1, "--username", "SP.Meharda", script=("create_sp_admin.py",))
    assert r.returncode == 0, r.stdout + r.stderr
    assert users_in(tmp_path / DB_FILE)["sp.meharda"][0] == "SUPERVISOR"


def test_weak_password_is_rejected(tmp_path, monkeypatch, capsys):
    r = run_cli(tmp_path, "password")                    # letters only
    assert r.returncode == 1 and "Mix letters" in r.stderr and "password" not in r.stdout
    assert not (tmp_path / DB_FILE).exists() or "sp" not in users_in(tmp_path / DB_FILE)

    # a weak SP_PASSWORD leaves an existing account as it was
    assert make_sp(monkeypatch, PW1, "sp.weak") == 0
    assert make_sp(monkeypatch, "short1", "sp.weak") == 1
    assert login("short1", "sp.weak")[1].status_code == 401
    assert login(PW1, "sp.weak")[1].status_code == 200

    # at the prompt, a weak password is refused and asked again
    monkeypatch.delenv("SP_PASSWORD")
    answers = iter(["abc", "12345678", PW2, PW2])
    monkeypatch.setattr(sp_admin.getpass, "getpass", lambda prompt="": next(answers))
    assert sp_admin.main(["--username", "sp.prompt"]) == 0
    out = capsys.readouterr().out
    assert "Use at least 8 characters." in out and "Mix letters" in out and PW2 not in out
    assert login(PW2, "sp.prompt")[1].status_code == 200


def test_rerun_resets_password_reactivates_and_signs_out_old_sessions(monkeypatch):
    assert make_sp(monkeypatch, PW1) == 0
    old, r = login(PW1)
    assert r.status_code == 200 and old.get("/api/auth/me").status_code == 200

    assert make_sp(monkeypatch, PW2) == 0                # reset the password
    assert old.get("/api/auth/me").status_code == 401    # the old session no longer works
    assert login(PW1)[1].status_code == 401
    assert login(PW2)[1].status_code == 200

    with SessionLocal() as s:                            # someone disabled and demoted the account
        u = s.query(User).filter_by(username="sp").one()
        u.active, u.role, u.must_change_password = False, "ANALYST", True
        s.commit()
    assert login(PW2)[1].status_code == 401
    assert make_sp(monkeypatch, PW3) == 0
    with SessionLocal() as s:
        u = s.query(User).filter_by(username="sp").one()
        assert (u.role, u.active, u.must_change_password) == ("SUPERVISOR", True, False)
    c, r = login(PW3)
    assert r.status_code == 200 and r.json()["role"] == "SUPERVISOR"


def test_sp_signs_in_and_reads_users_and_audit_log(monkeypatch):
    assert make_sp(monkeypatch, PW1) == 0
    c, r = login(PW1)
    assert r.status_code == 200, r.text
    me = r.json()
    assert (me["role"], me["designation"], me["must_change_password"]) == ("SUPERVISOR", "Superintendent of Police", False)

    users = c.get("/api/users")
    assert users.status_code == 200
    assert {"sp", "analyst", "io", "sho"} <= {u["username"] for u in users.json()}

    log = c.get("/api/audit")
    assert log.status_code == 200
    items = log.json()["items"]
    assert any(x["action"] == "login" and x["username"] == "sp" for x in items)
    assert any(x["action"] in ("user.created", "user.updated") and x["username"] == "terminal"
               and '"sp"' in x["detail"] for x in items)
