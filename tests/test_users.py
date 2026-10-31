from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.passwords import hash_password, verify_password
from app.core.schemas import User
from app.core.throttle import LoginThrottle
from app.db.models import InviteRow, UserRow
from app.db.session import make_engine, make_session_factory
from app.manage import main as manage_main
from app.services.users import (
    InviteInvalid,
    LoginLocked,
    UserError,
    UserService,
    hash_invite_token,
)


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
    with pytest.raises(UserError, match="is taken"):
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


# --- password change ------------------------------------------------------------------

def test_change_password_bumps_session_version(session: Session) -> None:
    users = UserService(session)
    user = users.create_user("davy", "old-password")
    changed = users.change_password(user.id, "old-password", "new-password")
    assert changed.session_version == user.session_version + 1
    assert users.authenticate("davy", "new-password") is not None
    assert users.authenticate("davy", "old-password") is None


def test_change_password_checks_current_and_new(session: Session) -> None:
    users = UserService(session)
    user = users.create_user("davy", "old-password")
    with pytest.raises(UserError, match="Current password is wrong"):
        users.change_password(user.id, "not-it-at-all", "new-password")
    with pytest.raises(UserError, match="at least 8"):
        users.change_password(user.id, "old-password", "short")


def test_change_password_locks_after_repeated_wrong_current(session: Session) -> None:
    users = UserService(session, LoginThrottle(max_failures=2))
    user = users.create_user("davy", "old-password")
    for _ in range(2):
        with pytest.raises(UserError):
            users.change_password(user.id, "wrong-guess", "new-password")
    with pytest.raises(LoginLocked):
        users.change_password(user.id, "old-password", "new-password")


def test_admin_reset_also_signs_out_everywhere(session: Session) -> None:
    users = UserService(session)
    user = users.create_user("davy", "old-password")
    users.set_password("davy", "new-password")
    assert users.get(user.id).session_version == user.session_version + 1


# --- invites --------------------------------------------------------------------------

class FakeNow:
    def __init__(self) -> None:
        self.value = datetime(2026, 1, 10, 12, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.value


@pytest.fixture
def now() -> FakeNow:
    return FakeNow()


@pytest.fixture
def admin_users(session: Session, now: FakeNow) -> tuple[UserService, User]:
    users = UserService(session, now=now)
    return users, users.create_user("davy", "long-enough-pw", is_admin=True)


def test_invite_creates_exactly_one_account(admin_users: tuple[UserService, User]) -> None:
    users, admin = admin_users
    token, invite = users.create_invite(admin)
    assert len(token) >= 30
    friend = users.sign_up(token, "Friend", "friend-password")
    assert friend.username == "friend"
    assert friend.is_admin is False
    assert users.list_invites(admin)[0].used_by == "friend"
    with pytest.raises(InviteInvalid):
        users.sign_up(token, "another", "another-password")


def test_only_the_token_hash_is_stored(session: Session, admin_users: tuple[UserService, User]) -> None:
    users, admin = admin_users
    token, _ = users.create_invite(admin)
    stored = session.scalars(select(InviteRow.token_hash)).one()
    assert token not in stored
    assert stored == hash_invite_token(token)


def test_invites_expire_after_a_week(admin_users: tuple[UserService, User], now: FakeNow) -> None:
    users, admin = admin_users
    token, invite = users.create_invite(admin)
    assert invite.expires_at - invite.created_at == timedelta(days=7)
    now.value += timedelta(days=7, seconds=1)
    with pytest.raises(InviteInvalid):
        users.check_invite(token)


@pytest.mark.parametrize("token", ["", "made-up-token", "x" * 40])
def test_unknown_tokens_are_invalid(admin_users: tuple[UserService, User], token: str) -> None:
    users, _ = admin_users
    with pytest.raises(InviteInvalid):
        users.check_invite(token)


def test_bad_sign_up_details_leave_the_invite_usable(admin_users: tuple[UserService, User]) -> None:
    users, admin = admin_users
    token, _ = users.create_invite(admin)
    users.session.commit()  # the invite was saved in an earlier request
    with pytest.raises(UserError, match="is taken"):
        users.sign_up(token, "davy", "friend-password")
    users.session.rollback()
    assert users.check_invite(token).used_at is None


def test_non_admins_cannot_manage_invites(admin_users: tuple[UserService, User]) -> None:
    users, admin = admin_users
    friend = users.create_user("friend", "friend-password")
    with pytest.raises(UserError, match="Only an admin"):
        users.create_invite(friend)
    with pytest.raises(UserError, match="Only an admin"):
        users.list_invites(friend)


def test_revoke_unused_invite(admin_users: tuple[UserService, User]) -> None:
    users, admin = admin_users
    token, invite = users.create_invite(admin)
    users.revoke_invite(admin, invite.id)
    with pytest.raises(InviteInvalid):
        users.check_invite(token)
    assert users.list_invites(admin) == []


def test_used_invites_stay_in_the_list(admin_users: tuple[UserService, User]) -> None:
    users, admin = admin_users
    token, invite = users.create_invite(admin)
    users.sign_up(token, "friend", "friend-password")
    users.revoke_invite(admin, invite.id)  # no effect once used
    assert [i.used_by for i in users.list_invites(admin)] == ["friend"]


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


def test_manage_admin_flag_and_set_admin(seeded_db_copy: Path, monkeypatch: pytest.MonkeyPatch,
                                         capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setenv("FOOD_MANAGER_DATABASE_URL", f"sqlite:///{seeded_db_copy.as_posix()}")
    monkeypatch.setattr("getpass.getpass", lambda prompt="": "long-enough-pw")
    assert manage_main(["add-user", "davy", "--admin"]) == 0
    assert manage_main(["add-user", "friend"]) == 0
    assert manage_main(["set-admin", "friend"]) == 0
    assert manage_main(["set-admin", "davy", "--off"]) == 0
    assert manage_main(["list-users"]) == 0
    lines = capsys.readouterr().out.strip().splitlines()
    assert lines[0] == "Created davy (admin)"
    assert lines[-2:] == ["davy", "friend (admin)"]


def test_manage_reports_errors(seeded_db_copy: Path, monkeypatch: pytest.MonkeyPatch,
                               capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setenv("FOOD_MANAGER_DATABASE_URL", f"sqlite:///{seeded_db_copy.as_posix()}")
    answers = iter(["long-enough-pw", "different-pw"])
    monkeypatch.setattr("getpass.getpass", lambda prompt="": next(answers))
    assert manage_main(["add-user", "friend"]) == 1
    assert "don't match" in capsys.readouterr().err
