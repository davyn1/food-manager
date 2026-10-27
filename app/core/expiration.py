"""Estimate expiration dates from shelf-life data. Pure functions, no I/O.

Rules (docs/DESIGN.md section 3):
- Unopened: clock_start + days for the current location. Uses FoodKeeper's minimum
  (conservative); falls back to the category default when the product has no figure.
- Opened (pantry/fridge): the sooner of the unopened date and opened_on + opened days.
  Opening never extends life. If the product has an unopened figure but no opened one,
  opening doesn't shorten it (FoodKeeper only lists opened times where they differ).
- Thawed in the fridge: FoodKeeper's "after thawing" figure when it has one.
- The storage clock restarts only when an item enters or leaves the freezer; moving
  between pantry and fridge keeps the original clock.
- User-entered dates are never changed here; `resolve_expiration` decides which date wins.
"""

from collections.abc import Callable
from datetime import date, timedelta

from app.core.schemas import (
    Category,
    DurationNote,
    EstimateBasis,
    EstimateFlag,
    ExpirationEstimate,
    ExpirationSource,
    ExpiryStatus,
    ItemState,
    Location,
    ResolvedExpiration,
    ShelfLifeProduct,
    StorageKey,
)

# "Indefinitely" still needs a date for sorting; ten years keeps it at the bottom.
INDEFINITE_DAYS = 3650

DefaultDays = Callable[[Category, Location, ItemState], int]

_UNOPENED_KEY: dict[Location, StorageKey] = {
    Location.PANTRY: StorageKey.PANTRY,
    Location.FRIDGE: StorageKey.FRIDGE,
    Location.FREEZER: StorageKey.FREEZER,
}
_OPENED_KEY: dict[Location, StorageKey] = {
    Location.PANTRY: StorageKey.PANTRY_OPENED,
    Location.FRIDGE: StorageKey.FRIDGE_OPENED,
}
_NOTE_FLAGS: dict[DurationNote, EstimateFlag] = {
    DurationNote.PACKAGE_DATE: EstimateFlag.USE_PACKAGE_DATE,
    DurationNote.WHEN_RIPE: EstimateFlag.WHEN_RIPE,
    DurationNote.NOT_RECOMMENDED: EstimateFlag.NOT_RECOMMENDED,
    DurationNote.INDEFINITE: EstimateFlag.INDEFINITE,
}


def restarts_clock(from_location: Location, to_location: Location) -> bool:
    """Whether moving an item starts a new storage clock (only freezer transitions do)."""
    return from_location is not to_location and Location.FREEZER in (from_location, to_location)


def _product_days(
    product: ShelfLifeProduct | None, key: StorageKey, flags: set[EstimateFlag]
) -> int | None:
    """Days for one storage key, recording any note as a flag. None means "no figure"."""
    if product is None or (duration := product.storage.get(key)) is None:
        return None
    if duration.note is not None:
        flags.add(_NOTE_FLAGS[duration.note])
        if duration.note is DurationNote.INDEFINITE:
            return INDEFINITE_DAYS
    return duration.min_days


def estimate_expiration(
    *,
    product: ShelfLifeProduct | None,
    category: Category,
    location: Location,
    state: ItemState,
    clock_start: date,
    default_days: DefaultDays,
    opened_on: date | None = None,
    thawed: bool = False,
) -> ExpirationEstimate:
    flags: set[EstimateFlag] = set()

    days = None
    if thawed and location is Location.FRIDGE:
        days = _product_days(product, StorageKey.FRIDGE_AFTER_THAW, flags)
    if days is None:
        days = _product_days(product, _UNOPENED_KEY[location], flags)
    if days is None:
        days, basis = default_days(category, location, ItemState.UNOPENED), EstimateBasis.CATEGORY_DEFAULT
    else:
        basis = EstimateBasis.PRODUCT
    expires_on = clock_start + timedelta(days=days)

    if state is ItemState.OPENED and location in _OPENED_KEY:
        opened_days = _product_days(product, _OPENED_KEY[location], flags)
        opened_basis = EstimateBasis.PRODUCT
        if opened_days is None and basis is EstimateBasis.CATEGORY_DEFAULT:
            opened_days = default_days(category, location, ItemState.OPENED)
            opened_basis = EstimateBasis.CATEGORY_DEFAULT
        if opened_days is not None:
            # Opened before it was thawed/moved: count from when this clock started.
            opened_start = max(opened_on or clock_start, clock_start)
            opened_expires_on = opened_start + timedelta(days=opened_days)
            if opened_expires_on < expires_on:
                expires_on, basis = opened_expires_on, opened_basis

    return ExpirationEstimate(expires_on=expires_on, basis=basis, flags=frozenset(flags))


def resolve_expiration(
    estimate: ExpirationEstimate, user_date: date | None, *, opened: bool
) -> ResolvedExpiration:
    """User dates always win; warn when an opened item's estimate is sooner than it."""
    if user_date is None:
        return ResolvedExpiration(expires_on=estimate.expires_on, source=ExpirationSource.ESTIMATED)
    return ResolvedExpiration(
        expires_on=user_date,
        source=ExpirationSource.USER,
        opened_sooner_than_user_date=opened and estimate.expires_on < user_date,
    )


def days_left(expires_on: date, today: date) -> int:
    return (expires_on - today).days


def expiry_status(expires_on: date, today: date, soon_days: int) -> ExpiryStatus:
    """Expired after its date; expiring soon from `soon_days` before through the day itself."""
    remaining = days_left(expires_on, today)
    if remaining < 0:
        return ExpiryStatus.EXPIRED
    if remaining <= soon_days:
        return ExpiryStatus.EXPIRING_SOON
    return ExpiryStatus.OK
