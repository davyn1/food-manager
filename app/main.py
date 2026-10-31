"""App factory. Run with:  uvicorn app.main:create_app --factory --reload"""

from collections.abc import Callable
from datetime import date
from urllib.parse import urlencode

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app import config
from app.core.throttle import LoginThrottle
from app.db.migrate import upgrade_to_head
from app.db.seed import load_data_files, seed_reference_data
from app.db.session import make_engine, make_session_factory
from app.db.shelf_life_repo import load_shelf_life_index
from app.web import account, auth, pages, pwa
from app.web.deps import LoginRequired
from app.web.templating import STATIC_DIR

SESSION_MAX_AGE = 180 * 24 * 60 * 60  # stay signed in on the phone for ~6 months


def create_app(
    db_url: str | None = None,
    today: Callable[[], date] = date.today,
    auto_setup: bool = True,
    secret_key: str | None = None,
    secure_cookies: bool | None = None,
) -> FastAPI:
    """Build the app. With auto_setup, migrate and seed the DB first (both idempotent)."""
    url = db_url or config.database_url()
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
    app.state.login_throttle = LoginThrottle()

    app.add_middleware(
        SessionMiddleware,
        secret_key=secret_key or config.secret_key(),
        session_cookie="pantry_session",
        max_age=SESSION_MAX_AGE,
        same_site="lax",  # not sent on cross-site form posts, which blocks CSRF
        https_only=config.secure_cookies() if secure_cookies is None else secure_cookies,
    )

    @app.exception_handler(LoginRequired)
    def redirect_to_login(request: Request, exc: LoginRequired) -> RedirectResponse:
        target = "/login" if exc.next_path == "/" else f"/login?{urlencode({'next': exc.next_path})}"
        return RedirectResponse(target, status_code=303)

    # HEAD too: hosting platforms' health checks often use it.
    @app.api_route("/health", methods=["GET", "HEAD"])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    app.include_router(pwa.router)
    app.include_router(auth.router)
    app.include_router(account.router)
    app.include_router(pages.router)
    return app
