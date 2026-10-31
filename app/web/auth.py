"""Login and logout. Accounts are created with `python -m app.manage add-user`."""

from typing import Annotated

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from app.services.users import LoginLocked, UserService
from app.web.deps import SESSION_USER_KEY
from app.web.pages import safe_next
from app.web.templating import templates

router = APIRouter()


def _login_page(request: Request, *, error: str | None = None, username: str = "",
                next_url: str = "/", status_code: int = 200) -> HTMLResponse:
    return templates.TemplateResponse(
        request, "login.html",
        {"error": error, "username": username, "next": next_url},
        status_code=status_code,
    )


@router.get("/login", response_class=HTMLResponse)
def login_form(request: Request, next: str | None = None) -> Response:
    if request.session.get(SESSION_USER_KEY):
        return RedirectResponse(safe_next(next, "/"), status_code=303)
    return _login_page(request, next_url=safe_next(next, "/"))


@router.post("/login")
def login(
    request: Request,
    username: Annotated[str, Form()] = "",
    password: Annotated[str, Form()] = "",
    next: Annotated[str | None, Form()] = None,
) -> Response:
    next_url = safe_next(next, "/")
    with request.app.state.session_factory() as session:
        users = UserService(session, request.app.state.login_throttle)
        try:
            user = users.authenticate(username, password)
        except LoginLocked:
            return _login_page(request, error="Too many attempts. Try again in 15 minutes.",
                               username=username, next_url=next_url, status_code=422)
    if user is None:
        return _login_page(request, error="Wrong username or password",
                           username=username, next_url=next_url, status_code=422)
    request.session.clear()
    request.session[SESSION_USER_KEY] = user.id
    return RedirectResponse(next_url, status_code=303)


@router.post("/logout")
def logout(request: Request) -> Response:
    request.session.clear()
    return RedirectResponse("/login", status_code=303)
