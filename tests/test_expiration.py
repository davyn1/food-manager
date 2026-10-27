from datetime import date

import pytest

from app.core.expiration import (
    INDEFINITE_DAYS,
    days_left,
    estimate_expiration,
    expiry_status,
    resolve_expiration,
    restarts_clock,
)
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
    ShelfLifeDuration,
    ShelfLifeProduct,
    StorageKey,
)

D0 = date(2026, 1, 10)

# Category defaults used when a product has no figure: easy-to-spot numbers.
DEFAULTS = {
    (Location.PANTRY, ItemState.UNOPENED): 100,
    (Location.PANTRY, ItemState.OPENED): 50,
    (Location.FRIDGE, ItemState.UNOPENED): 20,
    (Location.FRIDGE, ItemState.OPENED): 4,
    (Location.FREEZER, ItemState.UNOPENED): 200,
    (Location.FREEZER, ItemState.OPENED): 200,
}


def default_days(category: Category, location: Location, state: ItemState) -> int:
    return DEFAULTS[(location, state)]


def make_product(**storage: ShelfLifeDuration) -> ShelfLifeProduct:
    return ShelfLifeProduct(
        id=1, category=Category.DAIRY, source_category="x", name="Thing",
        storage={StorageKey(k): v for k, v in storage.items()},
    )


def days(n: int) -> ShelfLifeDuration:
    return ShelfLifeDuration(min_days=n, max_days=n + 2)


def note(n: DurationNote) -> ShelfLifeDuration:
    return ShelfLifeDuration(note=n)


def estimate(product: ShelfLifeProduct | None, location: Location, state: ItemState = ItemState.UNOPENED,
             **kwargs) -> ExpirationEstimate:
    return estimate_expiration(
        product=product, category=Category.DAIRY, location=location, state=state,
        clock_start=kwargs.pop("clock_start", D0), default_days=default_days, **kwargs,
    )


# --- unopened ---------------------------------------------------------------------

@pytest.mark.parametrize(
    ("location", "expected_days"),
    [(Location.PANTRY, 3), (Location.FRIDGE, 7), (Location.FREEZER, 90)],
)
def test_unopened_uses_product_minimum_for_location(location: Location, expected_days: int) -> None:
    product = make_product(pantry=days(3), fridge=days(7), freezer=days(90))
    result = estimate(product, location)
    assert (result.expires_on - D0).days == expected_days
    assert result.basis is EstimateBasis.PRODUCT


def test_no_product_uses_category_default() -> None:
    result = estimate(None, Location.FRIDGE)
    assert (result.expires_on - D0).days == 20
    assert result.basis is EstimateBasis.CATEGORY_DEFAULT


def test_product_missing_location_uses_category_default() -> None:
    result = estimate(make_product(fridge=days(7)), Location.FREEZER)
    assert (result.expires_on - D0).days == 200
    assert result.basis is EstimateBasis.CATEGORY_DEFAULT


def test_estimate_counts_from_clock_start() -> None:
    result = estimate(make_product(fridge=days(7)), Location.FRIDGE, clock_start=date(2026, 3, 1))
    assert result.expires_on == date(2026, 3, 8)


# --- notes -----------------------------------------------------------------------

def test_package_date_note_flags_and_falls_back() -> None:
    result = estimate(make_product(fridge=note(DurationNote.PACKAGE_DATE)), Location.FRIDGE)
    assert EstimateFlag.USE_PACKAGE_DATE in result.flags
    assert (result.expires_on - D0).days == 20


def test_when_ripe_note_flags_and_falls_back() -> None:
    result = estimate(make_product(pantry=note(DurationNote.WHEN_RIPE)), Location.PANTRY)
    assert result.flags == {EstimateFlag.WHEN_RIPE}
    assert result.basis is EstimateBasis.CATEGORY_DEFAULT


def test_not_recommended_location_flags_and_falls_back() -> None:
    result = estimate(make_product(freezer=note(DurationNote.NOT_RECOMMENDED)), Location.FREEZER)
    assert result.flags == {EstimateFlag.NOT_RECOMMENDED}
    assert (result.expires_on - D0).days == 200


def test_indefinite_note_uses_long_cap() -> None:
    result = estimate(make_product(pantry=note(DurationNote.INDEFINITE)), Location.PANTRY)
    assert result.flags == {EstimateFlag.INDEFINITE}
    assert (result.expires_on - D0).days == INDEFINITE_DAYS
    assert result.basis is EstimateBasis.PRODUCT


# --- opened ----------------------------------------------------------------------

def test_opened_uses_opened_figure_from_opened_date() -> None:
    product = make_product(fridge=days(30), fridge_opened=days(5))
    result = estimate(product, Location.FRIDGE, ItemState.OPENED, opened_on=date(2026, 1, 15))
    assert result.expires_on == date(2026, 1, 20)


def test_opening_never_extends_life() -> None:
    product = make_product(fridge=days(10), fridge_opened=days(30))
    result = estimate(product, Location.FRIDGE, ItemState.OPENED, opened_on=date(2026, 1, 15))
    assert result.expires_on == date(2026, 1, 20)  # unopened date: D0 + 10


def test_opened_without_opened_figure_keeps_product_figure() -> None:
    # e.g. butter: FoodKeeper lists one fridge time that applies opened or not.
    result = estimate(make_product(fridge=days(30)), Location.FRIDGE, ItemState.OPENED, opened_on=D0)
    assert (result.expires_on - D0).days == 30
    assert result.basis is EstimateBasis.PRODUCT


def test_opened_with_no_product_figure_uses_opened_category_default() -> None:
    # e.g. milk: fridge is "package date", no opened figure -> category opened default.
    product = make_product(fridge=note(DurationNote.PACKAGE_DATE))
    result = estimate(product, Location.FRIDGE, ItemState.OPENED, opened_on=D0)
    assert (result.expires_on - D0).days == 4
    assert result.basis is EstimateBasis.CATEGORY_DEFAULT
    assert EstimateFlag.USE_PACKAGE_DATE in result.flags


def test_opened_without_date_counts_from_clock_start() -> None:
    result = estimate(make_product(fridge=days(30), fridge_opened=days(5)), Location.FRIDGE, ItemState.OPENED)
    assert (result.expires_on - D0).days == 5


def test_opened_before_clock_start_counts_from_clock_start() -> None:
    # Opened, frozen, then thawed: the opened clock restarts with the thaw.
    product = make_product(fridge=days(30), fridge_opened=days(5))
    result = estimate(product, Location.FRIDGE, ItemState.OPENED,
                      opened_on=date(2025, 12, 1), clock_start=D0)
    assert (result.expires_on - D0).days == 5


def test_opened_does_not_shorten_freezer_life() -> None:
    product = make_product(freezer=days(90), fridge_opened=days(5))
    result = estimate(product, Location.FREEZER, ItemState.OPENED, opened_on=D0)
    assert (result.expires_on - D0).days == 90


# --- thawing and moves -----------------------------------------------------------

def test_thawed_in_fridge_uses_after_thaw_figure() -> None:
    product = make_product(fridge=days(7), fridge_after_thaw=days(2))
    assert (estimate(product, Location.FRIDGE, thawed=True).expires_on - D0).days == 2


def test_thawed_without_after_thaw_figure_uses_fridge_figure() -> None:
    product = make_product(fridge=days(7))
    assert (estimate(product, Location.FRIDGE, thawed=True).expires_on - D0).days == 7


@pytest.mark.parametrize(
    ("from_loc", "to_loc", "restarts"),
    [
        (Location.FRIDGE, Location.FREEZER, True),
        (Location.FREEZER, Location.FRIDGE, True),
        (Location.PANTRY, Location.FREEZER, True),
        (Location.PANTRY, Location.FRIDGE, False),
        (Location.FRIDGE, Location.PANTRY, False),
        (Location.FRIDGE, Location.FRIDGE, False),
    ],
)
def test_only_freezer_moves_restart_the_clock(from_loc: Location, to_loc: Location, restarts: bool) -> None:
    assert restarts_clock(from_loc, to_loc) is restarts


# --- resolving the user's date ---------------------------------------------------

EST = ExpirationEstimate(expires_on=date(2026, 1, 15), basis=EstimateBasis.PRODUCT)


def test_estimate_used_when_no_user_date() -> None:
    resolved = resolve_expiration(EST, None, opened=False)
    assert resolved.expires_on == date(2026, 1, 15)
    assert resolved.source is ExpirationSource.ESTIMATED


def test_user_date_always_wins() -> None:
    resolved = resolve_expiration(EST, date(2026, 2, 1), opened=False)
    assert resolved.expires_on == date(2026, 2, 1)
    assert resolved.source is ExpirationSource.USER
    assert resolved.opened_sooner_than_user_date is False


def test_warns_when_opened_estimate_is_sooner_than_user_date() -> None:
    resolved = resolve_expiration(EST, date(2026, 2, 1), opened=True)
    assert resolved.expires_on == date(2026, 2, 1)
    assert resolved.opened_sooner_than_user_date is True


def test_no_warning_when_user_date_is_sooner() -> None:
    resolved = resolve_expiration(EST, date(2026, 1, 12), opened=True)
    assert resolved.opened_sooner_than_user_date is False


# --- status ----------------------------------------------------------------------

@pytest.mark.parametrize(
    ("expires_on", "status"),
    [
        (date(2026, 1, 9), ExpiryStatus.EXPIRED),
        (date(2026, 1, 10), ExpiryStatus.EXPIRING_SOON),
        (date(2026, 1, 13), ExpiryStatus.EXPIRING_SOON),
        (date(2026, 1, 14), ExpiryStatus.OK),
    ],
)
def test_expiry_status_with_three_day_window(expires_on: date, status: ExpiryStatus) -> None:
    assert expiry_status(expires_on, today=D0, soon_days=3) is status


def test_days_left() -> None:
    assert days_left(date(2026, 1, 13), D0) == 3
    assert days_left(date(2026, 1, 8), D0) == -2


# --- end to end with real data ---------------------------------------------------

def test_real_chicken_thighs_in_fridge_then_freezer(real_index) -> None:
    product = real_index.match("chicken thighs").product
    fridge = estimate_expiration(
        product=product, category=Category.POULTRY, location=Location.FRIDGE,
        state=ItemState.UNOPENED, clock_start=D0, default_days=real_index.default_days,
    )
    freezer = estimate_expiration(
        product=product, category=Category.POULTRY, location=Location.FREEZER,
        state=ItemState.UNOPENED, clock_start=D0, default_days=real_index.default_days,
    )
    assert (fridge.expires_on - D0).days == 1
    assert (freezer.expires_on - D0).days == 270


def test_real_unmatched_meat_in_pantry_expires_same_day(real_index) -> None:
    result = estimate_expiration(
        product=None, category=Category.MEAT, location=Location.PANTRY,
        state=ItemState.UNOPENED, clock_start=D0, default_days=real_index.default_days,
    )
    assert result.expires_on == D0
