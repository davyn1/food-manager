"""Pydantic models shared across the app. Pure data, no I/O."""

from datetime import date
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


class ItemStatus(StrEnum):
    ACTIVE = "active"
    USED = "used"
    DISCARDED = "discarded"


class ItemEventType(StrEnum):
    ADDED = "added"
    OPENED = "opened"
    MOVED = "moved"
    PARTIALLY_USED = "partially_used"
    USED = "used"
    DISCARDED = "discarded"
    DATE_OVERRIDDEN = "date_overridden"


class AliasOrigin(StrEnum):
    CURATED = "curated"  # data/aliases_extra.json
    LEARNED = "learned"  # the user corrected a match


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


class ExpirationSource(StrEnum):
    ESTIMATED = "estimated"
    USER = "user"


class EstimateBasis(StrEnum):
    PRODUCT = "product"  # a FoodKeeper figure for this exact product
    CATEGORY_DEFAULT = "category_default"


class EstimateFlag(StrEnum):
    """Things the UI should tell the user about an estimate."""

    USE_PACKAGE_DATE = "use_package_date"  # source says: go by the printed date
    WHEN_RIPE = "when_ripe"  # keep at room temperature until ripe
    NOT_RECOMMENDED = "not_recommended"  # source advises against this storage location
    INDEFINITE = "indefinite"  # safe indefinitely; date is a best-quality cap


class ExpirationEstimate(BaseModel):
    model_config = ConfigDict(frozen=True)

    expires_on: date
    basis: EstimateBasis
    flags: frozenset[EstimateFlag] = frozenset()


class ResolvedExpiration(BaseModel):
    """The date the app shows, after applying a user-entered date if any."""

    model_config = ConfigDict(frozen=True)

    expires_on: date
    source: ExpirationSource
    # The item is opened and the opened-estimate is sooner than the user's printed date.
    opened_sooner_than_user_date: bool = False


class ExpiryStatus(StrEnum):
    EXPIRED = "expired"
    EXPIRING_SOON = "expiring_soon"
    OK = "ok"
