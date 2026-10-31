"""Accounts. There is no public sign-up: accounts are created with `python -m app.manage`."""

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.passwords import hash_password, verify_password
from app.core.schemas import User
from app.core.throttle import LoginThrottle
from app.db.models import UserRow

USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{2,31}$")
MIN_PASSWORD_LENGTH = 8
# Verified against when the username doesn't exist, so a wrong username takes as long
# as a wrong password and doesn't reveal which accounts exist.
_DUMMY_HASH = hash_password("not-a-real-password")


class UserError(Exception):
    """Invalid account input; the message is safe to show."""


class LoginLocked(Exception):
    pass


def normalize_username(username: str) -> str:
    return username.strip().lower()


def validate_password(password: str) -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise UserError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters")


class UserService:
    def __init__(self, session: Session, throttle: LoginThrottle | None = None) -> None:
        self.session = session
        self.throttle = throttle or LoginThrottle()

    def create_user(self, username: str, password: str) -> User:
        username = normalize_username(username)
        if not USERNAME_RE.match(username):
            raise UserError("Username must be 3-32 characters: letters, numbers, . _ -")
        if self._row_by_name(username) is not None:
            raise UserError(f"User {username!r} already exists")
        validate_password(password)
        row = UserRow(username=username, password_hash=hash_password(password))
        self.session.add(row)
        self.session.flush()
        return User.model_validate(row)

    def set_password(self, username: str, password: str) -> None:
        row = self._row_by_name(normalize_username(username))
        if row is None:
            raise UserError(f"No user named {username!r}")
        validate_password(password)
        row.password_hash = hash_password(password)
        self.session.flush()

    def authenticate(self, username: str, password: str) -> User | None:
        """The user if the password is right, else None. Raises LoginLocked when throttled."""
        key = normalize_username(username)
        if self.throttle.is_locked(key):
            raise LoginLocked
        row = self._row_by_name(key)
        if row is None:
            verify_password(password, _DUMMY_HASH)
            self.throttle.record_failure(key)
            return None
        if not verify_password(password, row.password_hash):
            self.throttle.record_failure(key)
            return None
        self.throttle.reset(key)
        return User.model_validate(row)

    def get(self, user_id: int) -> User | None:
        row = self.session.get(UserRow, user_id)
        return User.model_validate(row) if row else None

    def list_users(self) -> list[User]:
        return [User.model_validate(r) for r in self.session.scalars(select(UserRow).order_by(UserRow.username))]

    def _row_by_name(self, username: str) -> UserRow | None:
        return self.session.scalars(select(UserRow).where(UserRow.username == username)).one_or_none()
