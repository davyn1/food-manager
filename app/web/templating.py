"""Jinja setup and small display helpers shared by all templates."""

from datetime import date
from pathlib import Path

from fastapi.templating import Jinja2Templates

from app.core.expiration import days_left, expiry_status
from app.core.schemas import Category, EstimateFlag, ExpiryStatus, Item, ItemStatus, Location

WEB_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = WEB_DIR / "templates"
STATIC_DIR = WEB_DIR / "static"

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
    ItemStatus=ItemStatus,
    UNIT_SUGGESTIONS=UNIT_SUGGESTIONS,
    Category=Category,
    Location=Location,
    expiry_text=expiry_text,
    expiry_css=expiry_css,
    short_date=short_date,
    quantity_text=quantity_text,
)
