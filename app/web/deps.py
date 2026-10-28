from collections.abc import Iterator

from fastapi import Request

from app.services.pantry import PantryService


def get_pantry(request: Request) -> Iterator[PantryService]:
    """One session per request. Routes commit explicitly before responding."""
    session = request.app.state.session_factory()
    try:
        yield PantryService(session, request.app.state.index, today=request.app.state.today)
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
