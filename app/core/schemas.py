"""Pydantic models shared across the app. Pure data, no I/O."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class Category(StrEnum):
    PRODUCE = "produce"
    DAIRY = "dairy"
    MEAT = "meat"
    POULTRY = "poultry"
    SEAFOOD = "seafood"
    GRAINS = "grains"
    BAKED_GOODS = "baked_goods"
    CONDIMENTS = "condiments"
    BEVERAGES = "beverages"
    FROZEN = "frozen"
    SHELF_STABLE = "shelf_stable"
    DELI = "deli"
    PLANT_PROTEIN = "plant_protein"
    LEFTOVERS = "leftovers"
    OTHER = "other"


class Location(StrEnum):
    PANTRY = "pantry"
    FRIDGE = "fridge"
    FREEZER = "freezer"


class ItemState(StrEnum):
    UNOPENED = "unopened"
    OPENED = "opened"


class StorageKey(StrEnum):
    """Which shelf-life figure a duration describes."""

    PANTRY = "pantry"
    PANTRY_OPENED = "pantry_opened"
    FRIDGE = "fridge"
    FRIDGE_OPENED = "fridge_opened"
    FRIDGE_AFTER_THAW = "fridge_after_thaw"
    FREEZER = "freezer"


class DurationNote(StrEnum):
    """Non-numeric shelf-life answers from the source data."""

    INDEFINITE = "indefinite"
    PACKAGE_DATE = "package_date"  # "use the date printed on the package"
    WHEN_RIPE = "when_ripe"
    NOT_RECOMMENDED = "not_recommended"


class ShelfLifeDuration(BaseModel):
    model_config = ConfigDict(frozen=True)

    min_days: int | None = None
    max_days: int | None = None
    note: DurationNote | None = None


class ShelfLifeProduct(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: int
    category: Category
    source_category: str
    name: str
    subtitle: str | None = None
    keywords: list[str] = []
    storage: dict[StorageKey, ShelfLifeDuration] = {}
    tips: dict[StorageKey, str] = {}


class CategoryDefault(BaseModel):
    model_config = ConfigDict(frozen=True)

    category: Category
    location: Location
    state: ItemState
    days: int
