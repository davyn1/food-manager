from collections.abc import Iterator
from datetime import date, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.schemas import (
    AliasOrigin,
    Category,
    EstimateFlag,
    ExpirationSource,
    ItemCreate,
    ItemDraft,
    ItemEventType,
    ItemState,
    ItemStatus,
    Location,
)
from app.db.models import ItemRow, ShelfLifeAliasRow
from app.db.session import make_engine, make_session_factory
from app.db.shelf_life_repo import load_shelf_life_index
from app.services.pantry import InvalidOperation, ItemNotFound, PantryService
from app.services.users import UserService
from tests.conftest import Clock

D0 = date(2026, 1, 10)


def days_after(n: int) -> date:
    return D0 + timedelta(days=n)


@pytest.fixture
def clock() -> Clock:
    return Clock(D0)


@pytest.fixture
def session(seeded_db_copy: Path) -> Iterator[Session]:
    engine = make_engine(f"sqlite:///{seeded_db_copy.as_posix()}")
    with make_session_factory(engine)() as s:
        yield s
    engine.dispose()


@pytest.fixture
def pantry(session: Session, clock: Clock) -> PantryService:
    owner = UserService(session).create_user("owner", "long-enough-pw")
    return PantryService(session, load_shelf_life_index(session), owner=owner, today=clock)


@pytest.fixture
def other_pantry(session: Session, pantry: PantryService, clock: Clock) -> PantryService:
    """A second user's pantry, sharing the same database and matcher."""
    other = UserService(session).create_user("other", "long-enough-pw")
    return PantryService(session, pantry.index, owner=other, today=clock)


def events(session: Session, item_id: int) -> list[ItemEventType]:
    return [e.type for e in session.get(ItemRow, item_id).events]


# --- adding ----------------------------------------------------------------------

def test_add_matches_estimates_and_records_event(pantry: PantryService, session: Session) -> None:
    item = pantry.add_item(ItemCreate(name="Boneless chicken thighs", quantity=2, unit="lb"))
    assert item.shelf_life_id == 118
    assert item.shelf_life_name == "Chicken parts (legs or thighs)"
    assert item.category is Category.POULTRY
    assert item.location is Location.FRIDGE
    assert item.added_on == D0
    assert item.expires_on == days_after(1)
    assert item.expiration_source is ExpirationSource.ESTIMATED
    assert item.status is ItemStatus.ACTIVE
    assert events(session, item.id) == [ItemEventType.ADDED]


def test_add_with_printed_date_uses_it_but_keeps_estimate(pantry: PantryService) -> None:
    item = pantry.add_item(ItemCreate(name="chicken thighs", user_expires_on=days_after(4)))
    assert item.expires_on == days_after(4)
    assert item.expiration_source is ExpirationSource.USER
    assert item.estimated_expires_on == days_after(1)


@pytest.mark.parametrize(
    ("name", "location"),
    [
        ("canned tuna", Location.PANTRY),
        ("frozen peas", Location.FREEZER),
        ("butter", Location.FRIDGE),
        ("bananas", Location.PANTRY),
        ("mystery thing", Location.FRIDGE),
    ],
)
def test_add_suggests_location(pantry: PantryService, name: str, location: Location) -> None:
    assert pantry.add_item(ItemCreate(name=name)).location is location


def test_explicit_location_and_category_win(pantry: PantryService) -> None:
    item = pantry.add_item(ItemCreate(name="bananas", location=Location.FREEZER, category=Category.FROZEN))
    assert item.location is Location.FREEZER
    assert item.category is Category.FROZEN


def test_unmatched_item_uses_category_defaults(pantry: PantryService) -> None:
    item = pantry.add_item(ItemCreate(name="mystery thing"))
    assert item.shelf_life_id is None
    assert item.category is Category.OTHER
    assert item.expires_on == days_after(5)  # "other" fridge default


def test_package_date_flag_is_stored(pantry: PantryService) -> None:
    item = pantry.add_item(ItemCreate(name="milk"))
    assert EstimateFlag.USE_PACKAGE_DATE in item.estimate_flags
    assert EstimateFlag.USE_PACKAGE_DATE in pantry.get_item(item.id).estimate_flags


def test_add_opened_defaults_opened_date_to_added_date(pantry: PantryService) -> None:
    item = pantry.add_item(ItemCreate(name="milk", state=ItemState.OPENED))
    assert item.opened_on == D0
    assert item.expires_on == days_after(7)  # dairy opened fridge default


def test_add_rejects_opened_before_added(pantry: PantryService) -> None:
    with pytest.raises(InvalidOperation):
        pantry.add_item(ItemCreate(name="milk", added_on=D0, opened_on=days_after(-1)))


def test_blank_name_is_rejected() -> None:
    with pytest.raises(ValidationError):
        ItemCreate(name="   ")


def test_preview_does_not_save(pantry: PantryService) -> None:
    preview = pantry.preview(ItemCreate(name="chicken thighs"))
    assert preview.shelf_life_id == 118
    assert preview.estimated_expires_on == days_after(1)
    assert pantry.list_items() == []


def test_choosing_a_different_product_teaches_the_matcher(pantry: PantryService, session: Session) -> None:
    pantry.add_item(ItemCreate(name="Smoked salmon", shelf_life_id=167))
    assert session.get(ShelfLifeAliasRow, "smoked salmon").origin is AliasOrigin.LEARNED
    assert pantry.add_item(ItemCreate(name="smoked salmon")).shelf_life_id == 167


def test_choosing_the_automatic_match_learns_nothing(pantry: PantryService, session: Session) -> None:
    pantry.add_item(ItemCreate(name="chicken thighs", shelf_life_id=118))
    assert session.get(ShelfLifeAliasRow, "chicken thigh") is None


def test_add_items_from_drafts(pantry: PantryService) -> None:
    drafts = [
        ItemDraft(name="eggs", quantity=12, input_source="receipt", printed_expiration=days_after(30)),
        ItemDraft(name="apples", location=Location.FRIDGE),
    ]
    items = pantry.add_items([ItemCreate.from_draft(d) for d in drafts])
    assert [i.input_source for i in items] == ["receipt", "manual"]
    assert items[0].expires_on == days_after(30)
    assert items[1].location is Location.FRIDGE


# --- moving ----------------------------------------------------------------------

def test_move_to_freezer_restarts_clock(pantry: PantryService, session: Session, clock: Clock) -> None:
    item = pantry.add_item(ItemCreate(name="chicken thighs"))
    clock.value = days_after(1)
    moved = pantry.move_item(item.id, Location.FREEZER)
    assert moved.location_since == days_after(1)
    assert moved.expires_on == days_after(1 + 270)
    assert events(session, item.id) == [ItemEventType.ADDED, ItemEventType.MOVED]


def test_move_out_of_freezer_marks_thawed(pantry: PantryService, clock: Clock) -> None:
    item = pantry.add_item(ItemCreate(name="chicken thighs", location=Location.FREEZER))
    clock.value = days_after(30)
    thawed = pantry.move_item(item.id, Location.FRIDGE)
    assert thawed.thawed is True
    assert thawed.expires_on == days_after(31)


def test_move_back_into_freezer_clears_thawed(pantry: PantryService) -> None:
    item = pantry.add_item(ItemCreate(name="chicken thighs", location=Location.FREEZER))
    pantry.move_item(item.id, Location.FRIDGE)
    assert pantry.move_item(item.id, Location.FREEZER).thawed is False


def test_pantry_to_fridge_keeps_original_clock(pantry: PantryService, clock: Clock) -> None:
    item = pantry.add_item(ItemCreate(name="apples", location=Location.PANTRY))
    assert item.expires_on == days_after(21)
    clock.value = days_after(10)
    moved = pantry.move_item(item.id, Location.FRIDGE)
    assert moved.location_since == D0
    assert moved.expires_on == days_after(28)


def test_move_never_overwrites_user_date(pantry: PantryService) -> None:
    item = pantry.add_item(ItemCreate(name="chicken thighs", user_expires_on=days_after(4)))
    moved = pantry.move_item(item.id, Location.FREEZER)
    assert moved.expires_on == days_after(4)
    assert moved.expiration_source is ExpirationSource.USER
    assert moved.estimated_expires_on == days_after(270)


def test_move_to_same_location_is_a_no_op(pantry: PantryService, session: Session) -> None:
    item = pantry.add_item(ItemCreate(name="chicken thighs"))
    pantry.move_item(item.id, Location.FRIDGE)
    assert events(session, item.id) == [ItemEventType.ADDED]


# --- opening and dates -------------------------------------------------------------

def test_open_recalculates(pantry: PantryService, clock: Clock) -> None:
    item = pantry.add_item(ItemCreate(name="cheddar cheese block", category=Category.DAIRY, shelf_life_id=3))
    assert item.expires_on == days_after(180)
    clock.value = days_after(5)
    opened = pantry.open_item(item.id)
    assert opened.state is ItemState.OPENED
    assert opened.opened_on == days_after(5)
    assert opened.expires_on == days_after(5 + 21)


def test_open_twice_is_a_no_op(pantry: PantryService, session: Session) -> None:
    item = pantry.add_item(ItemCreate(name="milk"))
    pantry.open_item(item.id)
    pantry.open_item(item.id, on=days_after(3))
    assert pantry.get_item(item.id).opened_on == D0
    assert events(session, item.id) == [ItemEventType.ADDED, ItemEventType.OPENED]


def test_opening_keeps_user_date_and_warns_if_sooner(pantry: PantryService) -> None:
    item = pantry.add_item(ItemCreate(name="milk", user_expires_on=days_after(14)))
    opened = pantry.open_item(item.id)
    assert opened.expires_on == days_after(14)
    assert opened.estimated_expires_on == days_after(7)
    assert opened.opened_sooner_than_user_date is True


def test_set_and_clear_user_date(pantry: PantryService, session: Session) -> None:
    item = pantry.add_item(ItemCreate(name="chicken thighs"))
    with_date = pantry.set_user_expiration(item.id, days_after(3))
    assert (with_date.expires_on, with_date.expiration_source) == (days_after(3), ExpirationSource.USER)
    cleared = pantry.set_user_expiration(item.id, None)
    assert (cleared.expires_on, cleared.expiration_source) == (days_after(1), ExpirationSource.ESTIMATED)
    assert events(session, item.id).count(ItemEventType.DATE_OVERRIDDEN) == 2


def test_correcting_the_product_recalculates_and_learns(pantry: PantryService, session: Session) -> None:
    item = pantry.add_item(ItemCreate(name="smoked salmon"))
    assert item.expires_on == days_after(1)  # matched fresh fatty fish
    fixed = pantry.set_shelf_life_product(item.id, 167)  # cold smoked, vacuum pack
    assert fixed.expires_on == days_after(21)
    assert session.get(ShelfLifeAliasRow, "smoked salmon").product_id == 167
    assert pantry.preview(ItemCreate(name="Smoked Salmon")).shelf_life_id == 167


def test_clearing_the_product_uses_category_defaults(pantry: PantryService) -> None:
    item = pantry.add_item(ItemCreate(name="chicken thighs"))
    cleared = pantry.set_shelf_life_product(item.id, None)
    assert cleared.shelf_life_id is None
    assert cleared.expires_on == days_after(1)  # poultry fridge default


def test_action_date_before_added_is_rejected(pantry: PantryService) -> None:
    item = pantry.add_item(ItemCreate(name="milk"))
    with pytest.raises(InvalidOperation):
        pantry.open_item(item.id, on=days_after(-1))


# --- using up ----------------------------------------------------------------------

def test_partial_use_reduces_quantity_then_marks_used(pantry: PantryService, session: Session, clock: Clock) -> None:
    item = pantry.add_item(ItemCreate(name="chicken thighs", quantity=2, unit="lb"))
    assert pantry.use_partial(item.id, 0.5).quantity == 1.5
    clock.value = days_after(1)
    finished = pantry.use_partial(item.id, 1.5)
    assert finished.status is ItemStatus.USED
    assert finished.finished_on == days_after(1)
    assert events(session, item.id) == [ItemEventType.ADDED, ItemEventType.PARTIALLY_USED, ItemEventType.USED]


def test_partial_use_without_quantity_just_records_it(pantry: PantryService, session: Session) -> None:
    item = pantry.add_item(ItemCreate(name="ketchup"))
    after = pantry.use_partial(item.id)
    assert after.status is ItemStatus.ACTIVE
    assert after.quantity is None
    assert events(session, item.id)[-1] is ItemEventType.PARTIALLY_USED


def test_partial_use_rejects_non_positive_amount(pantry: PantryService) -> None:
    item = pantry.add_item(ItemCreate(name="rice", quantity=5))
    with pytest.raises(InvalidOperation):
        pantry.use_partial(item.id, 0)


def test_mark_used_and_discard(pantry: PantryService) -> None:
    used = pantry.mark_used(pantry.add_item(ItemCreate(name="milk")).id)
    discarded = pantry.discard(pantry.add_item(ItemCreate(name="eggs")).id)
    assert (used.status, used.finished_on) == (ItemStatus.USED, D0)
    assert (discarded.status, discarded.finished_on) == (ItemStatus.DISCARDED, D0)


def test_restore_undoes_used_and_discarded(pantry: PantryService, session: Session) -> None:
    item = pantry.add_item(ItemCreate(name="milk", quantity=1))
    pantry.mark_used(item.id)
    restored = pantry.restore(item.id)
    assert restored.status is ItemStatus.ACTIVE
    assert restored.finished_on is None
    assert [i.id for i in pantry.list_items()] == [item.id]
    pantry.discard(item.id)
    assert pantry.restore(item.id).status is ItemStatus.ACTIVE
    assert events(session, item.id)[-1] is ItemEventType.RESTORED


def test_restore_of_active_item_is_a_no_op(pantry: PantryService, session: Session) -> None:
    item = pantry.add_item(ItemCreate(name="milk"))
    pantry.restore(item.id)
    assert events(session, item.id) == [ItemEventType.ADDED]


def test_restore_is_owner_scoped(pantry: PantryService, other_pantry: PantryService) -> None:
    theirs = other_pantry.add_item(ItemCreate(name="eggs"))
    other_pantry.mark_used(theirs.id)
    with pytest.raises(ItemNotFound):
        pantry.restore(theirs.id)


def test_finished_items_cannot_be_changed(pantry: PantryService) -> None:
    item = pantry.mark_used(pantry.add_item(ItemCreate(name="milk")).id)
    for action in (
        lambda: pantry.open_item(item.id),
        lambda: pantry.move_item(item.id, Location.FREEZER),
        lambda: pantry.discard(item.id),
        lambda: pantry.use_partial(item.id),
    ):
        with pytest.raises(InvalidOperation, match="already used"):
            action()


def test_unknown_item_raises_not_found(pantry: PantryService) -> None:
    with pytest.raises(ItemNotFound):
        pantry.get_item(12345)


# --- queries -----------------------------------------------------------------------

def _add_expiring(pantry: PantryService, name: str, in_days: int) -> int:
    return pantry.add_item(ItemCreate(name=name, user_expires_on=days_after(in_days))).id


def test_list_items_sorted_by_expiration_and_active_only(pantry: PantryService) -> None:
    later = _add_expiring(pantry, "rice", 30)
    sooner = _add_expiring(pantry, "milk", 2)
    gone = _add_expiring(pantry, "eggs", 1)
    pantry.mark_used(gone)
    assert [i.id for i in pantry.list_items()] == [sooner, later]
    assert [i.id for i in pantry.list_items(status=ItemStatus.USED)] == [gone]


def test_list_items_by_location(pantry: PantryService) -> None:
    pantry.add_item(ItemCreate(name="canned tuna"))
    fridge_item = pantry.add_item(ItemCreate(name="milk"))
    assert [i.id for i in pantry.list_items(location=Location.FRIDGE)] == [fridge_item.id]


def test_expiring_soon_and_expired_windows(pantry: PantryService, clock: Clock) -> None:
    ids = {n: _add_expiring(pantry, f"item {n}", n) for n in (0, 1, 3, 4, 10)}
    clock.value = days_after(1)  # item 0 is now expired
    assert [i.id for i in pantry.expired()] == [ids[0]]
    assert [i.id for i in pantry.expiring_soon()] == [ids[1], ids[3], ids[4]]  # through D0+4
    assert [i.id for i in pantry.expiring_soon(days=2)] == [ids[1], ids[3]]


def test_expiring_soon_window_setting(pantry: PantryService) -> None:
    assert pantry.expiring_soon_days() == 3
    pantry.set_expiring_soon_days(7)
    assert pantry.expiring_soon_days() == 7
    for bad in (-1, 61):
        with pytest.raises(InvalidOperation):
            pantry.set_expiring_soon_days(bad)


# --- separate pantries -------------------------------------------------------------

def test_users_only_see_their_own_items(pantry: PantryService, other_pantry: PantryService,
                                        clock: Clock) -> None:
    mine = pantry.add_item(ItemCreate(name="milk", user_expires_on=days_after(1)))
    theirs = other_pantry.add_item(ItemCreate(name="eggs", user_expires_on=days_after(1)))
    assert [i.id for i in pantry.list_items()] == [mine.id]
    assert [i.id for i in other_pantry.list_items()] == [theirs.id]
    assert [i.id for i in pantry.expiring_soon()] == [mine.id]
    clock.value = days_after(5)
    assert [i.id for i in other_pantry.expired()] == [theirs.id]


def test_other_users_items_cannot_be_read_or_changed(pantry: PantryService,
                                                     other_pantry: PantryService) -> None:
    theirs = other_pantry.add_item(ItemCreate(name="eggs"))
    for action in (
        lambda: pantry.get_item(theirs.id),
        lambda: pantry.open_item(theirs.id),
        lambda: pantry.move_item(theirs.id, Location.FREEZER),
        lambda: pantry.set_user_expiration(theirs.id, D0),
        lambda: pantry.set_shelf_life_product(theirs.id, 27),
        lambda: pantry.use_partial(theirs.id),
        lambda: pantry.mark_used(theirs.id),
        lambda: pantry.discard(theirs.id),
    ):
        with pytest.raises(ItemNotFound):
            action()
    assert other_pantry.get_item(theirs.id).status is ItemStatus.ACTIVE


def test_expiring_soon_window_is_per_user(pantry: PantryService, other_pantry: PantryService) -> None:
    pantry.set_expiring_soon_days(10)
    assert other_pantry.expiring_soon_days() == 3
