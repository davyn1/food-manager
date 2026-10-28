"""Pantry operations: glue between the pure core (matching, estimation) and the DB.

Every change that can affect an item's expiration goes through `_recalculate`, which
refreshes the estimate and re-applies the rule that a user-entered date always wins.
The caller owns the transaction: methods flush but never commit.
"""

from collections.abc import Callable
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.expiration import estimate_expiration, resolve_expiration, restarts_clock
from app.core.normalize import normalize_name
from app.core.schemas import (
    Category,
    Item,
    ItemCreate,
    ItemEventType,
    ItemPreview,
    ItemState,
    ItemStatus,
    Location,
    ShelfLifeProduct,
)
from app.core.shelf_life import ShelfLifeIndex
from app.db.models import ItemEventRow, ItemRow, SettingRow
from app.db.shelf_life_repo import learn_alias

EXPIRING_SOON_SETTING = "expiring_soon_days"
DEFAULT_EXPIRING_SOON_DAYS = 3


class PantryError(Exception):
    """Base class for errors the UI should show to the user."""


class ItemNotFound(PantryError):
    def __init__(self, item_id: int) -> None:
        super().__init__(f"Item {item_id} not found")
        self.item_id = item_id


class InvalidOperation(PantryError):
    pass


def product_display_name(product: ShelfLifeProduct) -> str:
    return f"{product.name} ({product.subtitle})" if product.subtitle else product.name


class PantryService:
    def __init__(
        self, session: Session, index: ShelfLifeIndex, today: Callable[[], date] = date.today
    ) -> None:
        self.session = session
        self.index = index
        self.today = today

    # --- adding ------------------------------------------------------------------

    def preview(self, data: ItemCreate) -> ItemPreview:
        """Match, category, location and estimate an add would produce, without saving."""
        product, method, score = self._resolve_product(data)
        category = data.category or (product.category if product else Category.OTHER)
        location = data.location or self.index.suggest_location(product, category)
        start = data.added_on or self.today()
        estimate = estimate_expiration(
            product=product, category=category, location=location, state=data.state,
            clock_start=start, opened_on=data.opened_on, default_days=self.index.default_days,
        )
        return ItemPreview(
            shelf_life_id=product.id if product else None,
            shelf_life_name=product_display_name(product) if product else None,
            match_method=method,
            match_score=score,
            category=category,
            location=location,
            estimated_expires_on=estimate.expires_on,
            estimate_flags=estimate.flags,
        )

    def add_item(self, data: ItemCreate) -> Item:
        added_on = data.added_on or self.today()
        if data.opened_on is not None and data.opened_on < added_on:
            raise InvalidOperation("Opened date can't be before the date added")
        if data.shelf_life_id is not None:
            self._learn_if_corrected(data.name, data.shelf_life_id, data.category)

        preview = self.preview(data.model_copy(update={"added_on": added_on}))
        opened_on = data.opened_on or (added_on if data.state is ItemState.OPENED else None)
        row = ItemRow(
            name=data.name,
            normalized_name=normalize_name(data.name),
            shelf_life_id=preview.shelf_life_id,
            category=preview.category,
            quantity=data.quantity,
            unit=data.unit,
            location=preview.location,
            state=data.state,
            thawed=False,
            added_on=added_on,
            opened_on=opened_on,
            location_since=added_on,
            user_expires_on=data.user_expires_on,
            status=ItemStatus.ACTIVE,
            input_source=data.input_source,
            notes=data.notes,
        )
        self._recalculate(row)
        row.events.append(
            ItemEventRow(type=ItemEventType.ADDED, quantity_delta=data.quantity, to_location=row.location)
        )
        self.session.add(row)
        self.session.flush()
        return self._to_item(row)

    def add_items(self, items: list[ItemCreate]) -> list[Item]:
        return [self.add_item(data) for data in items]

    # --- changing ----------------------------------------------------------------

    def move_item(self, item_id: int, to_location: Location, on: date | None = None) -> Item:
        row = self._active_row(item_id)
        on = self._action_date(row, on)
        if row.location is to_location:
            return self._to_item(row)
        from_location = row.location
        if restarts_clock(from_location, to_location):
            row.location_since = on
            row.thawed = from_location is Location.FREEZER
        row.location = to_location
        self._recalculate(row)
        row.events.append(ItemEventRow(type=ItemEventType.MOVED, from_location=from_location, to_location=to_location))
        self.session.flush()
        return self._to_item(row)

    def open_item(self, item_id: int, on: date | None = None) -> Item:
        row = self._active_row(item_id)
        if row.state is ItemState.OPENED:
            return self._to_item(row)
        row.opened_on = self._action_date(row, on)
        row.state = ItemState.OPENED
        self._recalculate(row)
        row.events.append(ItemEventRow(type=ItemEventType.OPENED))
        self.session.flush()
        return self._to_item(row)

    def set_user_expiration(self, item_id: int, user_date: date | None) -> Item:
        """Set the printed date, or clear it (None) to go back to the estimate."""
        row = self._active_row(item_id)
        row.user_expires_on = user_date
        self._recalculate(row)
        row.events.append(ItemEventRow(type=ItemEventType.DATE_OVERRIDDEN))
        self.session.flush()
        return self._to_item(row)

    def set_shelf_life_product(self, item_id: int, product_id: int | None) -> Item:
        """Correct the matched product (None: use category defaults). Learns the alias."""
        row = self._active_row(item_id)
        if product_id is not None:
            self.index.product(product_id)  # raises KeyError for an unknown id
            learn_alias(self.session, row.name, product_id)
            self.index.add_alias(row.name, product_id)
        row.shelf_life_id = product_id
        self._recalculate(row)
        self.session.flush()
        return self._to_item(row)

    def use_partial(self, item_id: int, amount: float | None = None, on: date | None = None) -> Item:
        """Record using some of an item. Using up the whole quantity marks it used."""
        row = self._active_row(item_id)
        if amount is not None and amount <= 0:
            raise InvalidOperation("Amount used must be more than zero")
        if amount is not None and row.quantity is not None and amount >= row.quantity:
            return self.mark_used(item_id, on)
        if amount is not None and row.quantity is not None:
            row.quantity -= amount
        row.events.append(ItemEventRow(type=ItemEventType.PARTIALLY_USED, quantity_delta=-amount if amount else None))
        self.session.flush()
        return self._to_item(row)

    def mark_used(self, item_id: int, on: date | None = None) -> Item:
        return self._finish(item_id, ItemStatus.USED, ItemEventType.USED, on)

    def discard(self, item_id: int, on: date | None = None) -> Item:
        return self._finish(item_id, ItemStatus.DISCARDED, ItemEventType.DISCARDED, on)

    # --- queries -----------------------------------------------------------------

    def get_item(self, item_id: int) -> Item:
        return self._to_item(self._row(item_id))

    def list_items(self, status: ItemStatus = ItemStatus.ACTIVE, location: Location | None = None) -> list[Item]:
        """Items soonest-expiring first."""
        query = select(ItemRow).where(ItemRow.status == status)
        if location is not None:
            query = query.where(ItemRow.location == location)
        query = query.order_by(ItemRow.expires_on, ItemRow.name, ItemRow.id)
        return [self._to_item(row) for row in self.session.scalars(query)]

    def expiring_soon(self, days: int | None = None) -> list[Item]:
        """Active items expiring from today through `days` from now (default: the setting)."""
        days = self.expiring_soon_days() if days is None else days
        today = self.today()
        query = (
            select(ItemRow)
            .where(ItemRow.status == ItemStatus.ACTIVE)
            .where(ItemRow.expires_on >= today)
            .where(ItemRow.expires_on <= today + timedelta(days=days))
            .order_by(ItemRow.expires_on, ItemRow.name, ItemRow.id)
        )
        return [self._to_item(row) for row in self.session.scalars(query)]

    def expired(self) -> list[Item]:
        query = (
            select(ItemRow)
            .where(ItemRow.status == ItemStatus.ACTIVE)
            .where(ItemRow.expires_on < self.today())
            .order_by(ItemRow.expires_on, ItemRow.name, ItemRow.id)
        )
        return [self._to_item(row) for row in self.session.scalars(query)]

    def expiring_soon_days(self) -> int:
        setting = self.session.get(SettingRow, EXPIRING_SOON_SETTING)
        try:
            return int(setting.value) if setting else DEFAULT_EXPIRING_SOON_DAYS
        except ValueError:
            return DEFAULT_EXPIRING_SOON_DAYS

    def set_expiring_soon_days(self, days: int) -> None:
        if days < 0:
            raise InvalidOperation("The expiring-soon window can't be negative")
        self.session.merge(SettingRow(key=EXPIRING_SOON_SETTING, value=str(days)))
        self.session.flush()

    # --- internals ---------------------------------------------------------------

    def _resolve_product(self, data: ItemCreate) -> tuple[ShelfLifeProduct | None, str, float]:
        if data.shelf_life_id is not None:
            return self.index.product(data.shelf_life_id), "chosen", 1.0
        match = self.index.match(data.name, category=data.category)
        return match.product, str(match.method), match.score

    def _learn_if_corrected(self, name: str, product_id: int, category: Category | None) -> None:
        self.index.product(product_id)  # raises KeyError for an unknown id
        automatic = self.index.match(name, category=category).product
        if automatic is None or automatic.id != product_id:
            learn_alias(self.session, name, product_id)
            self.index.add_alias(name, product_id)

    def _recalculate(self, row: ItemRow) -> None:
        product = self.index.product(row.shelf_life_id) if row.shelf_life_id is not None else None
        estimate = estimate_expiration(
            product=product,
            category=row.category,
            location=row.location,
            state=row.state,
            clock_start=row.location_since,
            opened_on=row.opened_on,
            thawed=row.thawed,
            default_days=self.index.default_days,
        )
        resolved = resolve_expiration(estimate, row.user_expires_on, opened=row.state is ItemState.OPENED)
        row.estimated_expires_on = estimate.expires_on
        row.expires_on = resolved.expires_on
        row.expiration_source = resolved.source
        row.estimate_flags = sorted(estimate.flags)

    def _finish(self, item_id: int, status: ItemStatus, event: ItemEventType, on: date | None) -> Item:
        row = self._active_row(item_id)
        row.status = status
        row.finished_on = self._action_date(row, on)
        row.events.append(ItemEventRow(type=event))
        self.session.flush()
        return self._to_item(row)

    def _row(self, item_id: int) -> ItemRow:
        row = self.session.get(ItemRow, item_id)
        if row is None:
            raise ItemNotFound(item_id)
        return row

    def _active_row(self, item_id: int) -> ItemRow:
        row = self._row(item_id)
        if row.status is not ItemStatus.ACTIVE:
            raise InvalidOperation(f"{row.name} is already {row.status.value}")
        return row

    def _action_date(self, row: ItemRow, on: date | None) -> date:
        on = on or self.today()
        if on < row.added_on:
            raise InvalidOperation("That date is before the item was added")
        return on

    def _to_item(self, row: ItemRow) -> Item:
        item = Item.model_validate(row)
        if row.shelf_life_id is None:
            return item
        name = product_display_name(self.index.product(row.shelf_life_id))
        return item.model_copy(update={"shelf_life_name": name})
