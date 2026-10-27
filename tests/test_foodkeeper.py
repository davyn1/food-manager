from typing import Any

import pytest

from app.core.foodkeeper import (
    data_version,
    derive_category_defaults,
    parse_duration,
    parse_product,
    parse_products,
)
from app.core.schemas import (
    Category,
    DurationNote,
    ItemState,
    Location,
    ShelfLifeDuration,
    ShelfLifeProduct,
    StorageKey,
)


def _sheet(name: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Build a sheet in FoodKeeper's list-of-single-key-dicts layout."""
    return {"name": name, "data": [[{k: v} for k, v in row.items()] for row in rows]}


def _row(**fields: Any) -> dict[str, Any]:
    return {"ID": 1.0, "Category_ID": 7.0, "Name": "Butter", "Keywords": "Butter", **fields}


# --- parse_duration -----------------------------------------------------------

@pytest.mark.parametrize(
    ("low", "high", "metric", "expected"),
    [
        (1.0, 2.0, "Days", (1, 2)),
        (1.0, 2.0, "Weeks", (7, 14)),
        (6.0, 9.0, "Months", (180, 270)),
        (1.0, 1.0, "Year", (365, 365)),
        (2.0, 3.0, "Years", (730, 1095)),
        (2.0, 2.0, "Hours", (0, 0)),
    ],
)
def test_parse_duration_converts_units_to_days(low: float, high: float, metric: str, expected: tuple[int, int]) -> None:
    assert parse_duration(low, high, metric) == ShelfLifeDuration(min_days=expected[0], max_days=expected[1])


@pytest.mark.parametrize(
    ("metric", "note"),
    [
        ("Indefinitely", DurationNote.INDEFINITE),
        ("Package use-by date", DurationNote.PACKAGE_DATE),
        ("When Ripe", DurationNote.WHEN_RIPE),
        ("Not Recommended", DurationNote.NOT_RECOMMENDED),
    ],
)
def test_parse_duration_maps_non_numeric_metrics_to_notes(metric: str, note: DurationNote) -> None:
    assert parse_duration(None, None, metric) == ShelfLifeDuration(note=note)


def test_parse_duration_uses_max_when_min_missing() -> None:
    assert parse_duration(None, 18.0, "Months") == ShelfLifeDuration(min_days=540, max_days=540)


def test_parse_duration_orders_swapped_min_and_max() -> None:
    assert parse_duration(4.0, 2.0, "Days") == ShelfLifeDuration(min_days=2, max_days=4)


def test_parse_duration_without_metric_is_none() -> None:
    assert parse_duration(None, None, None) is None
    assert parse_duration("Or until best-by date.", None, None) is None


def test_parse_duration_rejects_unknown_metric() -> None:
    with pytest.raises(ValueError, match="Fortnights"):
        parse_duration(1, 2, "Fortnights")


# --- parse_product ------------------------------------------------------------

def test_parse_product_prefers_date_of_purchase_values() -> None:
    row = _row(
        Refrigerate_Min=1.0, Refrigerate_Max=2.0, Refrigerate_Metric="Days",
        DOP_Refrigerate_Min=1.0, DOP_Refrigerate_Max=2.0, DOP_Refrigerate_Metric="Weeks",
    )
    product = parse_product(row, {})
    assert product.storage[StorageKey.FRIDGE] == ShelfLifeDuration(min_days=7, max_days=14)


def test_parse_product_prefers_numbers_over_notes() -> None:
    row = _row(
        DOP_Refrigerate_Metric="Package use-by date",
        Refrigerate_Min=5.0, Refrigerate_Max=7.0, Refrigerate_Metric="Days",
    )
    assert parse_product(row, {}).storage[StorageKey.FRIDGE].min_days == 5


def test_parse_product_maps_all_storage_keys() -> None:
    row = _row(
        Pantry_Min=1.0, Pantry_Max=1.0, Pantry_Metric="Days",
        Pantry_After_Opening_Min=2.0, Pantry_After_Opening_Max=2.0, Pantry_After_Opening_Metric="Days",
        Refrigerate_Min=3.0, Refrigerate_Max=3.0, Refrigerate_Metric="Days",
        Refrigerate_After_Opening_Min=4.0, Refrigerate_After_Opening_Max=4.0, Refrigerate_After_Opening_Metric="Days",
        Refrigerate_After_Thawing_Min=5.0, Refrigerate_After_Thawing_Max=5.0, Refrigerate_After_Thawing_Metric="Days",
        Freeze_Min=6.0, Freeze_Max=6.0, Freeze_Metric="Days",
    )
    storage = parse_product(row, {}).storage
    assert {k: d.min_days for k, d in storage.items()} == {
        StorageKey.PANTRY: 1,
        StorageKey.PANTRY_OPENED: 2,
        StorageKey.FRIDGE: 3,
        StorageKey.FRIDGE_OPENED: 4,
        StorageKey.FRIDGE_AFTER_THAW: 5,
        StorageKey.FREEZER: 6,
    }


def test_parse_product_cleans_text_and_keywords() -> None:
    row = _row(
        Name="Milk ",
        Name_subtitle="  plain or   flavored ",
        Keywords="Milk,plain, flavored,milk,,",
    )
    product = parse_product(row, {7: "Dairy Products & Eggs"})
    assert product.name == "Milk"
    assert product.subtitle == "plain or flavored"
    assert product.keywords == ["milk", "plain", "flavored"]
    assert product.category is Category.DAIRY
    assert product.source_category == "Dairy Products & Eggs"


def test_parse_product_collects_tips_including_text_in_number_columns() -> None:
    row = _row(
        Pantry_tips="May be left at room temperature for 1 - 2 days.",
        Refrigerate_After_Thawing_Min="Or until best-by date.",
    )
    tips = parse_product(row, {}).tips
    assert tips[StorageKey.PANTRY] == "May be left at room temperature for 1 - 2 days."
    assert tips[StorageKey.FRIDGE_AFTER_THAW] == "Or until best-by date."


def test_unknown_category_id_maps_to_other() -> None:
    assert parse_product(_row(Category_ID=99.0), {}).category is Category.OTHER


# --- whole document -----------------------------------------------------------

def test_parse_products_and_version_from_document() -> None:
    doc = {
        "sheets": [
            _sheet("Version", [
                {"Data_Version_Number": 127.0, "Current_Version": None, "Modified_Date": "12-06-2017"},
                {"Data_Version_Number": 128.0, "Current_Version": "Yes", "Modified_Date": "09-06-2018"},
            ]),
            _sheet("Category", [{"ID": 15.0, "Category_Name": "Poultry", "Subcategory_Name": "Fresh"}]),
            _sheet("Product", [
                _row(ID=118.0, Category_ID=15.0, Name="Chicken parts", Name_subtitle="legs or thighs",
                     Keywords="Chicken parts,legs,thighs,chicken,leg,thigh",
                     Refrigerate_Min=1.0, Refrigerate_Max=2.0, Refrigerate_Metric="Days",
                     Freeze_Min=9.0, Freeze_Max=9.0, Freeze_Metric="Months"),
                _row(ID=2.0, Category_ID=15.0, Name="Other"),
            ]),
        ]
    }
    products = parse_products(doc)
    assert [p.id for p in products] == [2, 118]
    thighs = products[1]
    assert thighs.category is Category.POULTRY
    assert thighs.source_category == "Poultry / Fresh"
    assert thighs.storage[StorageKey.FREEZER].min_days == 270
    assert data_version(doc) == {"number": 128, "modified": "09-06-2018"}


# --- category defaults --------------------------------------------------------

def _product(pid: int, category: Category, **days: int) -> ShelfLifeProduct:
    storage = {StorageKey(k): ShelfLifeDuration(min_days=v, max_days=v) for k, v in days.items()}
    return ShelfLifeProduct(id=pid, category=category, source_category="x", name=f"p{pid}", storage=storage)


def _defaults_by_key(products: list[ShelfLifeProduct]) -> dict[tuple[Category, Location, ItemState], int]:
    return {(d.category, d.location, d.state): d.days for d in derive_category_defaults(products)}


def test_category_defaults_use_low_median_of_minimums() -> None:
    products = [
        _product(1, Category.DAIRY, fridge=7, fridge_opened=3, freezer=60, pantry=1),
        _product(2, Category.DAIRY, fridge=14, freezer=90, pantry=2),
        _product(3, Category.DAIRY, fridge=21, fridge_opened=5),
    ]
    d = _defaults_by_key(products)
    assert d[(Category.DAIRY, Location.FRIDGE, ItemState.UNOPENED)] == 14
    assert d[(Category.DAIRY, Location.FRIDGE, ItemState.OPENED)] == 3
    assert d[(Category.DAIRY, Location.FREEZER, ItemState.UNOPENED)] == 60
    assert d[(Category.DAIRY, Location.FREEZER, ItemState.OPENED)] == 60


def test_category_defaults_opened_never_exceeds_unopened() -> None:
    d = _defaults_by_key([_product(1, Category.CONDIMENTS, fridge=10, fridge_opened=60, pantry=1, freezer=1)])
    assert d[(Category.CONDIMENTS, Location.FRIDGE, ItemState.OPENED)] == 10


def test_category_defaults_fill_gaps_conservatively() -> None:
    products = [
        _product(1, Category.MEAT, fridge=3, freezer=120),
        _product(2, Category.GRAINS, pantry=365, fridge=180, freezer=240),
    ]
    d = _defaults_by_key(products)
    # No pantry data for meat: treat as "don't leave out".
    assert d[(Category.MEAT, Location.PANTRY, ItemState.UNOPENED)] == 0
    # No seafood data at all: fridge/freezer fall back to the all-products median.
    assert d[(Category.SEAFOOD, Location.FRIDGE, ItemState.UNOPENED)] == 3
    assert d[(Category.SEAFOOD, Location.FREEZER, ItemState.UNOPENED)] == 120


def test_perishable_categories_get_zero_pantry_days_despite_shelf_stable_variants() -> None:
    # e.g. canned chicken has a long pantry life, but raw chicken must not inherit it.
    d = _defaults_by_key([_product(1, Category.POULTRY, pantry=1825, fridge=1, freezer=180)])
    assert d[(Category.POULTRY, Location.PANTRY, ItemState.UNOPENED)] == 0
    assert d[(Category.POULTRY, Location.PANTRY, ItemState.OPENED)] == 0


def test_category_defaults_cover_every_category_location_and_state() -> None:
    defaults = derive_category_defaults([_product(1, Category.PRODUCE, pantry=3, fridge=5, freezer=200)])
    assert len(defaults) == len(Category) * len(Location) * len(ItemState)


def test_leftover_defaults_follow_usda_guidance() -> None:
    d = _defaults_by_key([_product(1, Category.PRODUCE, pantry=3, fridge=5, freezer=200)])
    assert d[(Category.LEFTOVERS, Location.FRIDGE, ItemState.UNOPENED)] == 3
    assert d[(Category.LEFTOVERS, Location.FREEZER, ItemState.UNOPENED)] == 90
    assert d[(Category.LEFTOVERS, Location.PANTRY, ItemState.UNOPENED)] == 0
