"""Accounts, one-time invite links, and password changes.

There is no open sign-up: an admin creates an invite link in the app (or an account with
`python -m app.manage add-user`), and each link creates exactly one account.
"""

import hashlib
import re
import secrets
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.passwords import hash_password, verify_password
from app.core.schemas import Invite, User
from app.core.throttle import LoginThrottle
from app.db.models import InviteRow, UserRow

USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{2,31}$")
MIN_PASSWORD_LENGTH = 8
INVITE_LIFETIME = timedelta(days=7)
# Verified against when the username doesn't exist, so a wrong username takes as long
# as a wrong password and doesn't reveal which accounts exist.
_DUMMY_HASH = hash_password("not-a-real-password")


class UserError(Exception):
    """Invalid account input; the message is safe to show."""


class InviteInvalid(UserError):
    def __init__(self) -> None:
        super().__init__("This invite link isn't valid anymore. Ask for a new one.")


class LoginLocked(Exception):
    pass


def normalize_username(username: str) -> str:
    return username.strip().lower()


def validate_password(password: str) -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise UserError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters")


def hash_invite_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _as_utc(value: datetime) -> datetime:
    """SQLite hands datetimes back without a timezone; they are stored as UTC."""
    return value if value.tzinfo else value.replace(tzinfo=UTC)


class UserService:
    def __init__(
        self,
        session: Session,
        throttle: LoginThrottle | None = None,
        now: Callable[[], datetime] = _utcnow,
    ) -> None:
        self.session = session
        self.throttle = throttle or LoginThrottle()
        self.now = now

    # --- accounts ------------------------------------------------------------------

    def create_user(self, username: str, password: str, *, is_admin: bool = False) -> User:
        username = normalize_username(username)
        if not USERNAME_RE.match(username):
            raise UserError("Username must be 3-32 characters: letters, numbers, . _ -")
        if self._row_by_name(username) is not None:
            raise UserError(f"The username {username!r} is taken")
        validate_password(password)
        row = UserRow(username=username, password_hash=hash_password(password), is_admin=is_admin)
        self.session.add(row)
        self.session.flush()
        return User.model_validate(row)

    def set_password(self, username: str, password: str) -> None:
        """Admin reset from the command line. Signs the user out everywhere."""
        row = self._row_by_name(normalize_username(username))
        if row is None:
            raise UserError(f"No user named {username!r}")
        self._replace_password(row, password)

    def set_admin(self, username: str, is_admin: bool = True) -> None:
        row = self._row_by_name(normalize_username(username))
        if row is None:
            raise UserError(f"No user named {username!r}")
        row.is_admin = is_admin
        self.session.flush()

    def change_password(self, user_id: int, current: str, new: str) -> User:
        """Signed-in change. Other devices are signed out; the caller re-signs this one."""
        row = self.session.get(UserRow, user_id)
        if row is None:
            raise UserError("Account not found")
        key = f"password-change:{user_id}"
        if self.throttle.is_locked(key):
            raise LoginLocked
        if not verify_password(current, row.password_hash):
            self.throttle.record_failure(key)
            raise UserError("Current password is wrong")
        self.throttle.reset(key)
        self._replace_password(row, new)
        return User.model_validate(row)

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

    # --- invites -------------------------------------------------------------------

    def create_invite(self, admin: User) -> tuple[str, Invite]:
        """A new one-time link token (shown once, never stored) and its record."""
        self._require_admin(admin)
        token = secrets.token_urlsafe(24)
        now = self.now()
        row = InviteRow(
            token_hash=hash_invite_token(token), created_by=admin.id,
            created_at=now, expires_at=now + INVITE_LIFETIME,
        )
        self.session.add(row)
        self.session.flush()
        return token, self._to_invite(row)

    def check_invite(self, token: str) -> Invite:
        return self._to_invite(self._usable_invite_row(token))

    def sign_up(self, token: str, username: str, password: str) -> User:
        """Create an account with an invite link, which is then used up."""
        invite = self._usable_invite_row(token)
        user = self.create_user(username, password)
        claimed = self.session.execute(
            update(InviteRow)
            .where(InviteRow.id == invite.id, InviteRow.used_at.is_(None))
            .values(used_at=self.now(), used_by=user.id)
        )
        if claimed.rowcount != 1:  # someone else used it a moment ago
            raise InviteInvalid
        self.session.flush()
        return user

    def list_invites(self, admin: User) -> list[Invite]:
        self._require_admin(admin)
        rows = self.session.scalars(select(InviteRow).order_by(InviteRow.created_at.desc(), InviteRow.id.desc()))
        return [self._to_invite(row) for row in rows]

    def revoke_invite(self, admin: User, invite_id: int) -> None:
        """Delete an unused invite so its link stops working."""
        self._require_admin(admin)
        row = self.session.get(InviteRow, invite_id)
        if row is not None and row.used_at is None:
            self.session.delete(row)
            self.session.flush()

    # --- internals -----------------------------------------------------------------

    def _replace_password(self, row: UserRow, password: str) -> None:
        validate_password(password)
        row.password_hash = hash_password(password)
        row.session_version += 1
        self.session.flush()

    def _require_admin(self, user: User) -> None:
        if not user.is_admin:
            raise UserError("Only an admin can manage invites")

    def _usable_invite_row(self, token: str) -> InviteRow:
        row = self.session.scalars(
            select(InviteRow).where(InviteRow.token_hash == hash_invite_token(token))
        ).one_or_none()
        if row is None or row.used_at is not None or _as_utc(row.expires_at) <= self.now():
            raise InviteInvalid
        return row

    def _to_invite(self, row: InviteRow) -> Invite:
        used_by = self.session.get(UserRow, row.used_by).username if row.used_by else None
        return Invite(
            id=row.id,
            created_at=_as_utc(row.created_at),
            expires_at=_as_utc(row.expires_at),
            used_at=_as_utc(row.used_at) if row.used_at else None,
            used_by=used_by,
        )

    def _row_by_name(self, username: str) -> UserRow | None:
        return self.session.scalars(select(UserRow).where(UserRow.username == username)).one_or_none()
