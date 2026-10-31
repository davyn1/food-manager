from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from app.core.passwords import hash_password, verify_password
from app.core.throttle import LoginThrottle
from app.db.models import UserRow
from app.db.session import make_engine, make_session_factory
from app.manage import main as manage_main
from app.services.users import LoginLocked, UserError, UserService


@pytest.fixture
def session(seeded_db_copy: Path) -> Iterator[Session]:
    engine = make_engine(f"sqlite:///{seeded_db_copy.as_posix()}")
    with make_session_factory(engine)() as s:
        yield s
    engine.dispose()


# --- password hashing ---------------------------------------------------------------

def test_hash_and_verify() -> None:
    stored = hash_password("correct horse")
    assert stored.startswith("scrypt$")
    assert "correct horse" not in stored
    assert verify_password("correct horse", stored)
    assert not verify_password("wrong horse", stored)


def test_same_password_gets_different_salts() -> None:
    assert hash_password("same-password") != hash_password("same-password")


@pytest.mark.parametrize("garbage", ["", "plain", "bcrypt$1$2$3$4$5", "scrypt$x$8$1$aa$bb"])
def test_malformed_hashes_never_verify(garbage: str) -> None:
    assert verify_password("anything", garbage) is False


# --- throttle -----------------------------------------------------------------------

def test_throttle_locks_after_max_failures_and_expires() -> None:
    clock = [0.0]
    throttle = LoginThrottle(max_failures=3, window_seconds=60, now=lambda: clock[0])
    for _ in range(3):
        assert not throttle.is_locked("davy")
        throttle.record_failure("davy")
    assert throttle.is_locked("davy")
    assert not throttle.is_locked("friend")
    clock[0] = 61
    assert not throttle.is_locked("davy")


def test_throttle_reset_clears_failures() -> None:
    throttle = LoginThrottle(max_failures=1)
    throttle.record_failure("davy")
    throttle.reset("davy")
    assert not throttle.is_locked("davy")


# --- user service -------------------------------------------------------------------

def test_create_and_authenticate(session: Session) -> None:
    users = UserService(session)
    created = users.create_user("  Davy ", "long-enough-pw")
    assert created.username == "davy"
    assert created.expiring_soon_days == 3
    assert users.authenticate("DAVY", "long-enough-pw") == created
    assert users.authenticate("davy", "wrong-password") is None
    assert users.authenticate("nobody", "long-enough-pw") is None
    assert users.get(created.id) == created


def test_password_is_stored_hashed(session: Session) -> None:
    UserService(session).create_user("davy", "long-enough-pw")
    row = session.query(UserRow).one()
    assert row.password_hash != "long-enough-pw"


@pytest.mark.parametrize(
    ("username", "password", "message"),
    [
        ("ab", "long-enough-pw", "Username must be"),
        ("bad name", "long-enough-pw", "Username must be"),
        ("davy", "short", "at least 8"),
    ],
)
def test_create_user_validation(session: Session, username: str, password: str, message: str) -> None:
    with pytest.raises(UserError, match=message):
        UserService(session).create_user(username, password)


def test_duplicate_username_rejected(session: Session) -> None:
    users = UserService(session)
    users.create_user("davy", "long-enough-pw")
    with pytest.raises(UserError, match="already exists"):
        users.create_user("DAVY", "another-password")


def test_set_password(session: Session) -> None:
    users = UserService(session)
    users.create_user("davy", "old-password")
    users.set_password("davy", "new-password")
    assert users.authenticate("davy", "old-password") is None
    assert users.authenticate("davy", "new-password") is not None
    with pytest.raises(UserError):
        users.set_password("nobody", "new-password")


def test_repeated_failures_lock_the_account(session: Session) -> None:
    users = UserService(session, LoginThrottle(max_failures=2))
    users.create_user("davy", "long-enough-pw")
    users.authenticate("davy", "nope-nope")
    users.authenticate("davy", "nope-nope")
    with pytest.raises(LoginLocked):
        users.authenticate("davy", "long-enough-pw")


def test_success_resets_failure_count(session: Session) -> None:
    users = UserService(session, LoginThrottle(max_failures=2))
    users.create_user("davy", "long-enough-pw")
    users.authenticate("davy", "nope-nope")
    assert users.authenticate("davy", "long-enough-pw") is not None
    users.authenticate("davy", "nope-nope")
    assert users.authenticate("davy", "long-enough-pw") is not None


# --- command line -------------------------------------------------------------------

def test_manage_add_and_list_users(seeded_db_copy: Path, monkeypatch: pytest.MonkeyPatch,
                                   capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setenv("FOOD_MANAGER_DATABASE_URL", f"sqlite:///{seeded_db_copy.as_posix()}")
    monkeypatch.setattr("getpass.getpass", lambda prompt="": "long-enough-pw")
    assert manage_main(["add-user", "Friend"]) == 0
    assert manage_main(["list-users"]) == 0
    out = capsys.readouterr().out
    assert "Created friend" in out
    assert out.strip().endswith("friend")


def test_manage_reports_errors(seeded_db_copy: Path, monkeypatch: pytest.MonkeyPatch,
                               capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setenv("FOOD_MANAGER_DATABASE_URL", f"sqlite:///{seeded_db_copy.as_posix()}")
    answers = iter(["long-enough-pw", "different-pw"])
    monkeypatch.setattr("getpass.getpass", lambda prompt="": next(answers))
    assert manage_main(["add-user", "friend"]) == 1
    assert "don't match" in capsys.readouterr().err
