from collections.abc import Iterator

from fastapi import Request

from app.services.pantry import PantryService
from app.services.users import UserService

SESSION_USER_KEY = "user_id"


class LoginRequired(Exception):
    """Raised by dependencies when nobody is signed in; handled as a redirect to /login."""

    def __init__(self, next_path: str) -> None:
        super().__init__(next_path)
        self.next_path = next_path


def get_pantry(request: Request) -> Iterator[PantryService]:
    """One DB session per request, for the signed-in user. Routes commit explicitly."""
    session = request.app.state.session_factory()
    try:
        user_id = request.session.get(SESSION_USER_KEY)
        user = UserService(session).get(user_id) if isinstance(user_id, int) else None
        if user is None:
            request.session.pop(SESSION_USER_KEY, None)
            path = request.url.path + (f"?{request.url.query}" if request.url.query else "")
            raise LoginRequired(path)
        request.state.user = user
        yield PantryService(session, request.app.state.index, today=request.app.state.today)
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
