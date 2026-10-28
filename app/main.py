"""App factory. Run with:  uvicorn app.main:create_app --factory --reload"""

from collections.abc import Callable
from datetime import date

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.config import database_url
from app.db.migrate import upgrade_to_head
from app.db.seed import load_data_files, seed_reference_data
from app.db.session import make_engine, make_session_factory
from app.db.shelf_life_repo import load_shelf_life_index
from app.web import pages, pwa
from app.web.templating import STATIC_DIR


def create_app(
    db_url: str | None = None,
    today: Callable[[], date] = date.today,
    auto_setup: bool = True,
) -> FastAPI:
    """Build the app. With auto_setup, migrate and seed the DB first (both idempotent)."""
    url = db_url or database_url()
    if auto_setup:
        upgrade_to_head(url)
    engine = make_engine(url)
    session_factory = make_session_factory(engine)
    if auto_setup:
        with session_factory() as session, session.begin():
            seed_reference_data(session, *load_data_files())
    with session_factory() as session:
        index = load_shelf_life_index(session)

    app = FastAPI(title="Food Manager")
    app.state.session_factory = session_factory
    app.state.index = index
    app.state.today = today

    # HEAD too: hosting platforms' health checks often use it.
    @app.api_route("/health", methods=["GET", "HEAD"])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    app.include_router(pwa.router)
    app.include_router(pages.router)
    return app
