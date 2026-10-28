"""HTML pages and form actions. Forms post and redirect (303); HTMX's hx-boost makes that
feel like a single-page app without separate partial endpoints, except the add preview."""

from datetime import date
from typing import Annotated, Any
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from pydantic import ValidationError

from app.core.schemas import Category, ItemCreate, ItemState, Location
from app.services.pantry import InvalidOperation, ItemNotFound, PantryService
from app.web.deps import get_pantry
from app.web.templating import templates

router = APIRouter()

Pantry = Annotated[PantryService, Depends(get_pantry)]
OptStr = Annotated[str | None, Form()]

# ?done=<key>&item=<id> notices. Fixed text only, never echoed from the URL.
NOTICES: dict[str, str] = {
    "added": "Added {name}",
    "used": "Marked {name} as used",
    "discarded": "Threw out {name}",
    "partial": "Recorded using some {name}",
}


# --- helpers ---------------------------------------------------------------------

def _blank_to_none(value: str | None) -> str | None:
    return value.strip() or None if value is not None else None


def _parse_date(value: str | None) -> date | None:
    value = _blank_to_none(value)
    if value is None:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise InvalidOperation("Please enter a valid date") from exc


def _parse_float(value: str | None) -> float | None:
    value = _blank_to_none(value)
    if value is None:
        return None
    try:
        return float(value)
    except ValueError as exc:
        raise InvalidOperation("Please enter a number") from exc


def _safe_next(next_url: str | None, default: str) -> str:
    """Only allow redirects to paths on this site."""
    if next_url and next_url.startswith("/") and not next_url.startswith("//") and "\\" not in next_url:
        return next_url
    return default


def _redirect(url: str, **params: Any) -> RedirectResponse:
    if params:
        separator = "&" if "?" in url else "?"
        url = f"{url}{separator}{urlencode(params)}"
    return RedirectResponse(url, status_code=303)


def _render(request: Request, pantry: PantryService, template: str, status_code: int = 200, **context: Any) -> HTMLResponse:
    today = pantry.today()
    return templates.TemplateResponse(
        request,
        template,
        {
            "today": today,
            "soon_days": pantry.expiring_soon_days(),
            "expired_count": len(pantry.expired()),
            "path": request.url.path,
            **context,
        },
        status_code=status_code,
    )


def _notice(pantry: PantryService, done: str | None, item_id: int | None) -> str | None:
    if done not in NOTICES or item_id is None:
        return None
    try:
        return NOTICES[done].format(name=pantry.get_item(item_id).name)
    except ItemNotFound:
        return None


def _item_or_404(request: Request, pantry: PantryService, item_id: int) -> Any:
    try:
        return pantry.get_item(item_id)
    except ItemNotFound:
        return _render(request, pantry, "not_found.html", status_code=404)


# --- home and adding ---------------------------------------------------------------

@router.get("/", response_class=HTMLResponse)
def home(request: Request, pantry: Pantry, done: str | None = None, item: int | None = None) -> HTMLResponse:
    return _render(
        request, pantry, "home.html",
        expired=pantry.expired(),
        soon=pantry.expiring_soon(),
        notice=_notice(pantry, done, item),
        just_added=done == "added",  # keep the keyboard up for the next item
        form={},
    )


def _item_create(
    name: str | None, quantity: str | None, unit: str | None, location: str | None,
    category: str | None, opened: str | None, user_expires_on: str | None,
) -> ItemCreate:
    return ItemCreate(
        name=name or "",
        quantity=_parse_float(quantity),
        unit=_blank_to_none(unit),
        location=Location(location) if _blank_to_none(location) else None,
        category=Category(category) if _blank_to_none(category) else None,
        state=ItemState.OPENED if opened else ItemState.UNOPENED,
        user_expires_on=_parse_date(user_expires_on),
    )


@router.get("/add/preview", response_class=HTMLResponse)
def add_preview(
    request: Request, pantry: Pantry,
    name: str | None = None, quantity: str | None = None, unit: str | None = None,
    location: str | None = None, category: str | None = None, opened: str | None = None,
    user_expires_on: str | None = None,
) -> Response:
    if not _blank_to_none(name):
        return HTMLResponse("")
    try:
        data = _item_create(name, quantity, unit, location, category, opened, user_expires_on)
    except (ValidationError, InvalidOperation, ValueError):
        return HTMLResponse("")
    return templates.TemplateResponse(
        request, "partials/preview.html",
        {"preview": pantry.preview(data), "data": data, "today": pantry.today(), "soon_days": pantry.expiring_soon_days()},
    )


@router.post("/items")
def add_item(
    request: Request, pantry: Pantry,
    name: OptStr = None, quantity: OptStr = None, unit: OptStr = None, location: OptStr = None,
    category: OptStr = None, opened: OptStr = None, user_expires_on: OptStr = None,
) -> Response:
    form = {
        "name": name, "quantity": quantity, "unit": unit, "location": location,
        "category": category, "opened": opened, "user_expires_on": user_expires_on,
    }
    try:
        data = _item_create(name, quantity, unit, location, category, opened, user_expires_on)
        item = pantry.add_item(data)
    except ValidationError as exc:
        error = "Please enter a name" if any(e["loc"] == ("name",) for e in exc.errors()) else "Please check the details"
        return _home_with_error(request, pantry, form, error)
    except (InvalidOperation, ValueError) as exc:
        return _home_with_error(request, pantry, form, str(exc))
    pantry.session.commit()
    return _redirect("/", done="added", item=item.id)


def _home_with_error(request: Request, pantry: PantryService, form: dict[str, Any], error: str) -> HTMLResponse:
    pantry.session.rollback()
    return _render(
        request, pantry, "home.html", status_code=422,
        expired=pantry.expired(), soon=pantry.expiring_soon(), form=form, error=error, notice=None,
    )


# --- lists -------------------------------------------------------------------------

@router.get("/items", response_class=HTMLResponse)
def list_items(
    request: Request, pantry: Pantry,
    location: Location | None = None, sort: str = "expires", done: str | None = None, item: int | None = None,
) -> HTMLResponse:
    items = pantry.list_items(location=location)
    if sort == "name":
        items.sort(key=lambda i: i.name.lower())
    return _render(
        request, pantry, "items.html",
        items=items, location=location, sort=sort, notice=_notice(pantry, done, item),
    )


@router.get("/expired", response_class=HTMLResponse)
def expired(request: Request, pantry: Pantry, done: str | None = None, item: int | None = None) -> HTMLResponse:
    return _render(request, pantry, "expired.html", items=pantry.expired(), notice=_notice(pantry, done, item))


# --- one item ----------------------------------------------------------------------

@router.get("/items/{item_id}", response_class=HTMLResponse)
def item_detail(request: Request, pantry: Pantry, item_id: int) -> Response:
    item = _item_or_404(request, pantry, item_id)
    if isinstance(item, Response):
        return item
    return _render(request, pantry, "item.html", item=item, error=None)


def _act(request: Request, pantry: PantryService, item_id: int, action: Any, next_url: str | None,
         done: str | None = None) -> Response:
    """Run an item action, commit, and redirect; show errors on the item page."""
    try:
        result = action()
    except ItemNotFound:
        return _render(request, pantry, "not_found.html", status_code=404)
    except (InvalidOperation, KeyError) as exc:
        pantry.session.rollback()
        message = str(exc) if isinstance(exc, InvalidOperation) else "Unknown product"
        item = _item_or_404(request, pantry, item_id)
        if isinstance(item, Response):
            return item
        return _render(request, pantry, "item.html", status_code=422, item=item, error=message)
    pantry.session.commit()
    target = _safe_next(next_url, f"/items/{item_id}")
    if done:
        return _redirect(target, done=done, item=result.id)
    return _redirect(target)


@router.post("/items/{item_id}/move")
def move(request: Request, pantry: Pantry, item_id: int, location: Annotated[Location, Form()],
         next: OptStr = None) -> Response:
    return _act(request, pantry, item_id, lambda: pantry.move_item(item_id, location), next)


@router.post("/items/{item_id}/open")
def open_(request: Request, pantry: Pantry, item_id: int, next: OptStr = None) -> Response:
    return _act(request, pantry, item_id, lambda: pantry.open_item(item_id), next)


@router.post("/items/{item_id}/use")
def use_some(request: Request, pantry: Pantry, item_id: int, amount: OptStr = None, next: OptStr = None) -> Response:
    return _act(request, pantry, item_id, lambda: pantry.use_partial(item_id, _parse_float(amount)), next)


@router.post("/items/{item_id}/used")
def used(request: Request, pantry: Pantry, item_id: int, next: OptStr = None) -> Response:
    return _act(request, pantry, item_id, lambda: pantry.mark_used(item_id), next, done="used")


@router.post("/items/{item_id}/discard")
def discard(request: Request, pantry: Pantry, item_id: int, next: OptStr = None) -> Response:
    return _act(request, pantry, item_id, lambda: pantry.discard(item_id), next, done="discarded")


@router.post("/items/{item_id}/date")
def set_date(request: Request, pantry: Pantry, item_id: int, user_expires_on: OptStr = None,
             clear: OptStr = None) -> Response:
    def action() -> Any:
        new_date = None if clear else _parse_date(user_expires_on)
        if new_date is None and not clear:
            raise InvalidOperation("Pick a date, or use the estimate instead")
        return pantry.set_user_expiration(item_id, new_date)
    return _act(request, pantry, item_id, action, None)


@router.get("/items/{item_id}/match", response_class=HTMLResponse)
def match_page(request: Request, pantry: Pantry, item_id: int, q: str | None = None) -> Response:
    item = _item_or_404(request, pantry, item_id)
    if isinstance(item, Response):
        return item
    query = q if q is not None else item.name
    candidates = pantry.index.search(query, category=item.category, limit=12)
    return _render(request, pantry, "match.html", item=item, q=query, candidates=candidates)


@router.post("/items/{item_id}/match")
def set_match(request: Request, pantry: Pantry, item_id: int, product_id: OptStr = None) -> Response:
    def action() -> Any:
        chosen = _blank_to_none(product_id)
        if chosen is not None and not chosen.isdigit():
            raise InvalidOperation("Unknown product")
        return pantry.set_shelf_life_product(item_id, int(chosen) if chosen else None)
    return _act(request, pantry, item_id, action, None)


# --- settings ----------------------------------------------------------------------

@router.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request, pantry: Pantry, saved: bool = False) -> HTMLResponse:
    return _render(request, pantry, "settings.html", saved=saved, error=None)


@router.post("/settings")
def save_settings(request: Request, pantry: Pantry, expiring_soon_days: OptStr = None) -> Response:
    try:
        value = _parse_float(expiring_soon_days)
        if value is None or value != int(value) or value > 60:
            raise InvalidOperation("Enter a whole number of days from 0 to 60")
        pantry.set_expiring_soon_days(int(value))
    except InvalidOperation as exc:
        pantry.session.rollback()
        return _render(request, pantry, "settings.html", status_code=422, saved=False, error=str(exc))
    pantry.session.commit()
    return _redirect("/settings", saved="true")
