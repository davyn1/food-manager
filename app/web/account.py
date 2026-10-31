"""Signed-in account pages: change password, and invite links (admins only)."""

from typing import Annotated

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from app.services.pantry import PantryService
from app.services.users import LoginLocked, UserError, UserService
from app.web.deps import sign_in
from app.web.pages import Pantry, redirect, render

router = APIRouter()


def _users(request: Request, pantry: PantryService) -> UserService:
    return UserService(pantry.session, request.app.state.login_throttle)


@router.post("/settings/password")
def change_password(
    request: Request,
    pantry: Pantry,
    current: Annotated[str, Form()] = "",
    new: Annotated[str, Form()] = "",
    confirm: Annotated[str, Form()] = "",
) -> Response:
    try:
        if new != confirm:
            raise UserError("The new passwords don't match")
        user = _users(request, pantry).change_password(request.state.user.id, current, new)
    except LoginLocked:
        error = "Too many wrong attempts. Try again in 15 minutes."
    except UserError as exc:
        error = str(exc)
    else:
        pantry.session.commit()
        sign_in(request, user)  # keep this device signed in with the new session version
        return redirect("/settings", saved="password")
    pantry.session.rollback()
    return render(request, pantry, "settings.html", status_code=422, saved=None, error=None,
                   password_error=error)


# --- invites (admins) -------------------------------------------------------------------

def _invites_page(request: Request, pantry: PantryService, *, new_link: str | None = None) -> HTMLResponse:
    invites = _users(request, pantry).list_invites(request.state.user)
    return render(request, pantry, "invites.html", invites=invites, new_link=new_link,
                   now=_users(request, pantry).now())


def _not_admin(request: Request, pantry: PantryService) -> HTMLResponse | None:
    if request.state.user.is_admin:
        return None
    return render(request, pantry, "not_found.html", status_code=404)


@router.get("/invites", response_class=HTMLResponse)
def invites(request: Request, pantry: Pantry) -> HTMLResponse:
    return _not_admin(request, pantry) or _invites_page(request, pantry)


@router.post("/invites", response_class=HTMLResponse)
def create_invite(request: Request, pantry: Pantry) -> HTMLResponse:
    """Create a link and show it right away. It's shown only this once (only its hash is kept),
    so this responds with the page instead of redirecting."""
    if (denied := _not_admin(request, pantry)) is not None:
        return denied
    token, _ = _users(request, pantry).create_invite(request.state.user)
    pantry.session.commit()
    link = f"{str(request.base_url).rstrip('/')}/signup/{token}"
    return _invites_page(request, pantry, new_link=link)


@router.post("/invites/{invite_id}/revoke")
def revoke_invite(request: Request, pantry: Pantry, invite_id: int) -> Response:
    if (denied := _not_admin(request, pantry)) is not None:
        return denied
    _users(request, pantry).revoke_invite(request.state.user, invite_id)
    pantry.session.commit()
    return RedirectResponse("/invites", status_code=303)
