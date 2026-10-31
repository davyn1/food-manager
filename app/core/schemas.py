"""Pydantic models shared across the app. Pure data, no I/O."""

from datetime import date, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator


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


# --- users -------------------------------------------------------------------------


class User(BaseModel):
    model_config = ConfigDict(from_attributes=True, frozen=True)

    id: int
    username: str
    expiring_soon_days: int
    is_admin: bool = False
    session_version: int = 1


class Invite(BaseModel):
    """A sign-up link as shown to the admin (the token itself is never stored)."""

    model_config = ConfigDict(frozen=True)

    id: int
    created_at: datetime
    expires_at: datetime
    used_at: datetime | None = None
    used_by: str | None = None  # username of whoever signed up with it


# --- items -------------------------------------------------------------------------


class ItemDraft(BaseModel):
    """A proposed item from any input source (manual form, photo, receipt).

    Only the name is required; anything recognized with less certainty is left None.
    Drafts are never saved directly: the user confirms them as ItemCreate first.
    """

    name: str
    category: Category | None = None
    quantity: float | None = None
    unit: str | None = None
    location: Location | None = None
    state: ItemState | None = None
    printed_expiration: date | None = None
    input_source: str = "manual"
    confidence: float | None = None  # 0..1 from recognizers; None for manual entry
    raw_text: str | None = None  # what the recognizer saw, for the confirm screen


class ItemCreate(BaseModel):
    """A user-confirmed new item. Unset fields are filled in by the pantry service."""

    name: str = Field(min_length=1, max_length=200)
    category: Category | None = None  # None: take it from the matched product
    shelf_life_id: int | None = None  # set when the user picked the product explicitly
    quantity: float | None = Field(default=None, gt=0)
    unit: str | None = Field(default=None, max_length=32)
    location: Location | None = None  # None: suggested from the product/category
    state: ItemState = ItemState.UNOPENED
    added_on: date | None = None  # None: today
    opened_on: date | None = None
    user_expires_on: date | None = None
    input_source: str = "manual"
    notes: str | None = None

    @field_validator("name")
    @classmethod
    def _strip_name(cls, value: str) -> str:
        value = " ".join(value.split())
        if not value:
            raise ValueError("name must not be blank")
        return value

    @classmethod
    def from_draft(cls, draft: ItemDraft) -> "ItemCreate":
        return cls(
            name=draft.name,
            category=draft.category,
            quantity=draft.quantity,
            unit=draft.unit,
            location=draft.location,
            state=draft.state or ItemState.UNOPENED,
            user_expires_on=draft.printed_expiration,
            input_source=draft.input_source,
        )


class Item(BaseModel):
    """An item as stored, plus a few derived fields for display."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    category: Category
    shelf_life_id: int | None
    shelf_life_name: str | None = None  # e.g. "Chicken parts (legs or thighs)"
    quantity: float | None
    unit: str | None
    location: Location
    state: ItemState
    thawed: bool
    added_on: date
    opened_on: date | None
    location_since: date
    estimated_expires_on: date
    user_expires_on: date | None
    expires_on: date
    expiration_source: ExpirationSource
    estimate_flags: frozenset[EstimateFlag] = frozenset()
    status: ItemStatus
    finished_on: date | None
    input_source: str
    notes: str | None

    @property
    def opened_sooner_than_user_date(self) -> bool:
        return (
            self.state is ItemState.OPENED
            and self.user_expires_on is not None
            and self.estimated_expires_on < self.user_expires_on
        )


class ItemPreview(BaseModel):
    """What adding an item would produce, for the add form's live preview."""

    model_config = ConfigDict(frozen=True)

    shelf_life_id: int | None
    shelf_life_name: str | None
    match_method: str
    match_score: float
    category: Category
    location: Location
    estimated_expires_on: date
    estimate_flags: frozenset[EstimateFlag] = frozenset()
