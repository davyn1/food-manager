"""Login, logout, and sign-up through one-time invite links (all public routes)."""

from typing import Annotated

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from app.services.users import InviteInvalid, LoginLocked, UserError, UserService
from app.web.deps import SESSION_USER_KEY, sign_in
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
    sign_in(request, user)
    return RedirectResponse(next_url, status_code=303)


@router.post("/logout")
def logout(request: Request) -> Response:
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


# --- sign-up with a one-time invite link (public) -------------------------------------

def _signup_page(request: Request, token: str, *, invalid: bool = False, error: str | None = None,
                 username: str = "", status_code: int = 200) -> HTMLResponse:
    return templates.TemplateResponse(
        request, "signup.html",
        {"token": token, "invalid": invalid, "error": error, "username": username,
         "signed_in": bool(request.session.get(SESSION_USER_KEY))},
        status_code=status_code,
    )


@router.get("/signup/{token}", response_class=HTMLResponse)
def signup_form(request: Request, token: str) -> HTMLResponse:
    with request.app.state.session_factory() as session:
        try:
            UserService(session).check_invite(token)
        except InviteInvalid:
            return _signup_page(request, token, invalid=True, status_code=404)
    return _signup_page(request, token)


@router.post("/signup/{token}")
def signup(
    request: Request,
    token: str,
    username: Annotated[str, Form()] = "",
    password: Annotated[str, Form()] = "",
    confirm: Annotated[str, Form()] = "",
) -> Response:
    with request.app.state.session_factory() as session:
        try:
            if password != confirm:
                UserService(session).check_invite(token)  # an invalid link still says so
                raise UserError("The passwords don't match")
            user = UserService(session).sign_up(token, username, password)
            session.commit()
        except InviteInvalid:
            return _signup_page(request, token, invalid=True, status_code=404)
        except UserError as exc:
            session.rollback()
            return _signup_page(request, token, error=str(exc), username=username, status_code=422)
    sign_in(request, user)
    return RedirectResponse("/", status_code=303)
