"""SQLAlchemy ORM models. Enums are stored as their string values (no native DB enums),
so adding a category later doesn't need a schema change."""

from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import JSON, Date, DateTime, Enum, Float, ForeignKey, Index, MetaData, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app.core.schemas import (
    AliasOrigin,
    Category,
    CategoryDefault,
    ExpirationSource,
    ItemEventType,
    ItemState,
    ItemStatus,
    Location,
    ShelfLifeProduct,
)

# Stable constraint names so Alembic batch migrations on SQLite can find them.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


def _enum(enum_cls: type[StrEnum]) -> Enum:
    return Enum(
        enum_cls,
        native_enum=False,
        length=32,
        values_callable=lambda members: [m.value for m in members],
    )


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class UserRow(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(32), unique=True)  # lowercase
    password_hash: Mapped[str] = mapped_column(String(200))
    expiring_soon_days: Mapped[int] = mapped_column(default=3, server_default="3")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class ShelfLifeProductRow(Base):
    """One FoodKeeper product. Durations and tips are JSON shaped like ShelfLifeProduct."""

    __tablename__ = "shelf_life_products"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=False)
    category: Mapped[Category] = mapped_column(_enum(Category))
    source_category: Mapped[str] = mapped_column(String(100))
    name: Mapped[str] = mapped_column(String(200))
    subtitle: Mapped[str | None] = mapped_column(String(300))
    keywords: Mapped[list[str]] = mapped_column(JSON, default=list)
    storage: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    tips: Mapped[dict[str, str]] = mapped_column(JSON, default=dict)

    def to_schema(self) -> ShelfLifeProduct:
        return ShelfLifeProduct.model_validate(
            {
                "id": self.id,
                "category": self.category,
                "source_category": self.source_category,
                "name": self.name,
                "subtitle": self.subtitle,
                "keywords": self.keywords,
                "storage": self.storage,
                "tips": self.tips,
            }
        )


class ShelfLifeAliasRow(Base):
    __tablename__ = "shelf_life_aliases"

    alias: Mapped[str] = mapped_column(String(200), primary_key=True)  # normalized name
    product_id: Mapped[int] = mapped_column(ForeignKey("shelf_life_products.id"))
    origin: Mapped[AliasOrigin] = mapped_column(_enum(AliasOrigin))


class CategoryDefaultRow(Base):
    __tablename__ = "category_defaults"

    category: Mapped[Category] = mapped_column(_enum(Category), primary_key=True)
    location: Mapped[Location] = mapped_column(_enum(Location), primary_key=True)
    state: Mapped[ItemState] = mapped_column(_enum(ItemState), primary_key=True)
    days: Mapped[int]

    def to_schema(self) -> CategoryDefault:
        return CategoryDefault(category=self.category, location=self.location, state=self.state, days=self.days)


class ItemRow(Base):
    __tablename__ = "items"
    __table_args__ = (Index("ix_items_owner_status_expires_on", "owner_id", "status", "expires_on"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    # Each user has their own pantry; every query filters on this.
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(200))
    normalized_name: Mapped[str] = mapped_column(String(200), index=True)
    shelf_life_id: Mapped[int | None] = mapped_column(ForeignKey("shelf_life_products.id"))
    category: Mapped[Category] = mapped_column(_enum(Category))
    quantity: Mapped[float | None] = mapped_column(Float)
    unit: Mapped[str | None] = mapped_column(String(32))
    location: Mapped[Location] = mapped_column(_enum(Location))
    state: Mapped[ItemState] = mapped_column(_enum(ItemState), default=ItemState.UNOPENED)
    # Moved from the freezer to the fridge; selects FoodKeeper's "after thawing" figure.
    thawed: Mapped[bool] = mapped_column(default=False)
    added_on: Mapped[date] = mapped_column(Date)
    opened_on: Mapped[date | None] = mapped_column(Date)
    # Start of the current storage clock; only reset by freezer moves.
    location_since: Mapped[date] = mapped_column(Date)
    estimated_expires_on: Mapped[date] = mapped_column(Date)
    user_expires_on: Mapped[date | None] = mapped_column(Date)
    # Effective date (user date if set, else the estimate), stored for sorting.
    expires_on: Mapped[date] = mapped_column(Date)
    expiration_source: Mapped[ExpirationSource] = mapped_column(_enum(ExpirationSource))
    # EstimateFlag values from the latest estimate, e.g. ["use_package_date"].
    estimate_flags: Mapped[list[str]] = mapped_column(JSON, default=list, server_default="[]")
    status: Mapped[ItemStatus] = mapped_column(_enum(ItemStatus), default=ItemStatus.ACTIVE)
    finished_on: Mapped[date | None] = mapped_column(Date)
    input_source: Mapped[str] = mapped_column(String(32), default="manual")
    notes: Mapped[str | None] = mapped_column(Text)

    events: Mapped[list["ItemEventRow"]] = relationship(
        back_populates="item", cascade="all, delete-orphan", order_by="ItemEventRow.id"
    )


class ItemEventRow(Base):
    __tablename__ = "item_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id", ondelete="CASCADE"), index=True)
    type: Mapped[ItemEventType] = mapped_column(_enum(ItemEventType))
    quantity_delta: Mapped[float | None] = mapped_column(Float)
    from_location: Mapped[Location | None] = mapped_column(_enum(Location))
    to_location: Mapped[Location | None] = mapped_column(_enum(Location))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    item: Mapped[ItemRow] = relationship(back_populates="events")


class StapleRow(Base):
    """Ingredients assumed always on hand for recipe matching."""

    __tablename__ = "staples"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)  # normalized


class SettingRow(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(String(500))
