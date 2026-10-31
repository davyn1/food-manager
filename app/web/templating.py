"""Jinja setup and small display helpers shared by all templates."""

import hashlib
from datetime import date, timedelta
from pathlib import Path

from fastapi.templating import Jinja2Templates

from app.core.expiration import days_left, expiry_status
from app.core.schemas import Category, EstimateFlag, ExpiryStatus, Item, ItemStatus, Location

WEB_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = WEB_DIR / "templates"
STATIC_DIR = WEB_DIR / "static"
# Files the service worker caches; their URLs carry ?v=STATIC_VERSION so a change
# to any of them reaches phones on the next visit.
VERSIONED_ASSETS = ("app.css", "app.js", "vendor/htmx.min.js")


def _static_version() -> str:
    digest = hashlib.sha256()
    for name in VERSIONED_ASSETS:
        digest.update((STATIC_DIR / name).read_bytes())
    return digest.hexdigest()[:10]


STATIC_VERSION = _static_version()

CATEGORY_LABELS: dict[Category, str] = {c: c.value.replace("_", " ").capitalize() for c in Category}
LOCATION_LABELS: dict[Location, str] = {loc: loc.value.capitalize() for loc in Location}
FLAG_TEXT: dict[EstimateFlag, str] = {
    EstimateFlag.USE_PACKAGE_DATE: "Best to go by the printed date",
    EstimateFlag.WHEN_RIPE: "Keep at room temperature until ripe",
    EstimateFlag.NOT_RECOMMENDED: "Not recommended to store it here",
    EstimateFlag.INDEFINITE: "Keeps indefinitely; date is for best quality",
}
STATUS_LABELS: dict[ItemStatus, str] = {
    ItemStatus.ACTIVE: "In stock",
    ItemStatus.USED: "Used",
    ItemStatus.DISCARDED: "Thrown out",
}
UNIT_SUGGESTIONS = ("pcs", "lb", "oz", "g", "kg", "ml", "l", "cup", "pack", "can", "bag", "bunch")


def expiry_text(expires_on: date, today: date) -> str:
    remaining = days_left(expires_on, today)
    if remaining < -1:
        return f"Expired {-remaining} days ago"
    if remaining == -1:
        return "Expired yesterday"
    if remaining == 0:
        return "Expires today"
    if remaining == 1:
        return "Expires tomorrow"
    if remaining < 60:
        return f"{remaining} days left"
    if remaining < 730:
        return f"{round(remaining / 30)} months left"
    return f"{round(remaining / 365)} years left"


def expiry_css(expires_on: date, today: date, soon_days: int) -> str:
    return {
        ExpiryStatus.EXPIRED: "expired",
        ExpiryStatus.EXPIRING_SOON: "soon",
        ExpiryStatus.OK: "ok",
    }[expiry_status(expires_on, today, soon_days)]


def dot_level(expires_on: date, today: date, soon_days: int) -> str:
    """Day-dot color: expired, now (today/tomorrow), soon (within the window), ok, later (months)."""
    remaining = days_left(expires_on, today)
    if remaining < 0:
        return "expired"
    if remaining <= 1:
        return "now"
    if remaining <= soon_days:
        return "soon"
    if remaining < 60:
        return "ok"
    return "later"


def dot_parts(expires_on: date, today: date) -> tuple[str, str]:
    """What's written on a day dot: a marker number and a small unit under it.

    ("today", ""), ("1", "day"), ("3", "days"), ("−2", "days") for past dates,
    ("4", "mo"), ("2", "yr"). The marker font is capitals-only, so units stay in the body font.
    """
    remaining = days_left(expires_on, today)
    if remaining == 0:
        return "today", ""
    if remaining < 0:
        return f"−{-remaining}", "day" if remaining == -1 else "days"
    if remaining < 60:
        return str(remaining), "day" if remaining == 1 else "days"
    if remaining < 730:
        return str(round(remaining / 30)), "mo"
    return str(round(remaining / 365)), "yr"


QUICK_DATES: tuple[tuple[str, int], ...] = (("3 days", 3), ("1 week", 7), ("2 weeks", 14), ("1 month", 30))


def date_choices(today: date) -> list[tuple[str, str]]:
    """One-tap "goes bad in…" choices for food the app doesn't know: (label, ISO date)."""
    return [(label, (today + timedelta(days=days)).isoformat()) for label, days in QUICK_DATES]


def short_date(value: date) -> str:
    return f"{value:%a} {value:%b} {value.day}"


def quantity_text(item: Item) -> str:
    if item.quantity is None:
        return ""
    number = f"{item.quantity:g}"
    return f"{number} {item.unit}" if item.unit else number


templates = Jinja2Templates(directory=TEMPLATES_DIR)
templates.env.globals.update(
    CATEGORY_LABELS=CATEGORY_LABELS,
    LOCATION_LABELS=LOCATION_LABELS,
    FLAG_TEXT=FLAG_TEXT,
    STATUS_LABELS=STATUS_LABELS,
    STATIC_VERSION=STATIC_VERSION,
    ItemStatus=ItemStatus,
    UNIT_SUGGESTIONS=UNIT_SUGGESTIONS,
    Category=Category,
    Location=Location,
    expiry_text=expiry_text,
    expiry_css=expiry_css,
    dot_level=dot_level,
    dot_parts=dot_parts,
    date_choices=date_choices,
    short_date=short_date,
    quantity_text=quantity_text,
)
