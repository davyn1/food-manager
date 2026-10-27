"""Convert the USDA FSIS FoodKeeper dataset into the app's shelf-life schema.

Pure functions over the already-parsed JSON document; file and network I/O lives in
scripts/import_foodkeeper.py.

FoodKeeper JSON layout: {"sheets": [{"name": ..., "data": [[{col: val}, ...], ...]}]}
Each product has Min/Max/Metric triples per storage condition. "DOP_" variants count
from the date of purchase; the plain variants are used when no DOP value exists.
"""

import math
from collections.abc import Iterable
from statistics import median_low
from typing import Any

from app.core.schemas import (
    Category,
    CategoryDefault,
    DurationNote,
    ItemState,
    Location,
    ShelfLifeDuration,
    ShelfLifeProduct,
    StorageKey,
)

METRIC_DAYS: dict[str, float] = {
    "Hours": 1 / 24,
    "Days": 1,
    "Weeks": 7,
    "Months": 30,
    "Year": 365,
    "Years": 365,
}

METRIC_NOTES: dict[str, DurationNote] = {
    "Indefinitely": DurationNote.INDEFINITE,
    "Package use-by date": DurationNote.PACKAGE_DATE,
    "When Ripe": DurationNote.WHEN_RIPE,
    "Not Recommended": DurationNote.NOT_RECOMMENDED,
}

# FoodKeeper category ID -> app category. IDs from the dataset's "Category" sheet.
CATEGORY_MAP: dict[int, Category] = {
    1: Category.OTHER,  # Baby Food
    2: Category.BAKED_GOODS,
    3: Category.SHELF_STABLE,  # Baked Goods / Baking and Cooking: flour, oils, spices
    4: Category.BAKED_GOODS,
    5: Category.BEVERAGES,
    6: Category.CONDIMENTS,  # Condiments, Sauces & Canned Goods
    7: Category.DAIRY,  # Dairy Products & Eggs
    8: Category.FROZEN,
    9: Category.GRAINS,  # Grains, Beans & Pasta
    10: Category.MEAT,
    11: Category.MEAT,
    12: Category.MEAT,
    13: Category.MEAT,
    14: Category.POULTRY,
    15: Category.POULTRY,
    16: Category.POULTRY,
    17: Category.POULTRY,
    18: Category.PRODUCE,
    19: Category.PRODUCE,
    20: Category.SEAFOOD,
    21: Category.SEAFOOD,
    22: Category.SEAFOOD,
    23: Category.SHELF_STABLE,
    24: Category.PLANT_PROTEIN,
    25: Category.DELI,
}

# Storage key -> source column prefixes, in order of preference.
STORAGE_COLUMNS: dict[StorageKey, tuple[str, ...]] = {
    StorageKey.PANTRY: ("DOP_Pantry", "Pantry"),
    StorageKey.PANTRY_OPENED: ("Pantry_After_Opening",),
    StorageKey.FRIDGE: ("DOP_Refrigerate", "Refrigerate"),
    StorageKey.FRIDGE_OPENED: ("Refrigerate_After_Opening",),
    StorageKey.FRIDGE_AFTER_THAW: ("Refrigerate_After_Thawing",),
    StorageKey.FREEZER: ("DOP_Freeze", "Freeze"),
}

TIP_COLUMNS: dict[StorageKey, tuple[str, ...]] = {
    StorageKey.PANTRY: ("DOP_Pantry_tips", "Pantry_tips"),
    StorageKey.FRIDGE: ("DOP_Refrigerate_tips", "Refrigerate_tips"),
    StorageKey.FREEZER: ("DOP_Freeze_Tips", "Freeze_Tips"),
}

# USDA guidance for cooked leftovers (no FoodKeeper category covers them):
# refrigerate 3-4 days, freeze 3-4 months, never leave out more than 2 hours.
LEFTOVER_DEFAULTS: dict[Location, int] = {
    Location.PANTRY: 0,
    Location.FRIDGE: 3,
    Location.FREEZER: 90,
}

# Categories whose typical item must not sit at room temperature. Their only pantry
# data in FoodKeeper comes from canned/dried variants (canned chicken, jerky, powdered
# milk), which would make an unmatched fresh item look safe for months.
PERISHABLE_CATEGORIES: frozenset[Category] = frozenset(
    {Category.DAIRY, Category.MEAT, Category.POULTRY, Category.SEAFOOD, Category.DELI, Category.FROZEN}
)

_LOCATION_KEYS: dict[Location, tuple[StorageKey, StorageKey | None]] = {
    Location.PANTRY: (StorageKey.PANTRY, StorageKey.PANTRY_OPENED),
    Location.FRIDGE: (StorageKey.FRIDGE, StorageKey.FRIDGE_OPENED),
    Location.FREEZER: (StorageKey.FREEZER, None),
}


def sheet_rows(doc: dict[str, Any], sheet_name: str) -> list[dict[str, Any]]:
    """Flatten one sheet's list-of-single-key-dicts rows into plain dicts."""
    for sheet in doc["sheets"]:
        if sheet["name"] == sheet_name:
            rows = []
            for raw_row in sheet["data"]:
                row: dict[str, Any] = {}
                for cell in raw_row:
                    row.update(cell)
                rows.append(row)
            return rows
    raise KeyError(f"FoodKeeper sheet not found: {sheet_name}")


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def parse_duration(min_value: Any, max_value: Any, metric: Any) -> ShelfLifeDuration | None:
    """Convert one Min/Max/Metric triple to whole days (rounded down, conservative).

    Returns None when the triple carries no usable information.
    Raises ValueError for an unknown metric so new source vocabulary is noticed.
    """
    if metric is None:
        return None
    metric = str(metric).strip()
    if metric in METRIC_NOTES:
        return ShelfLifeDuration(note=METRIC_NOTES[metric])
    if metric not in METRIC_DAYS:
        raise ValueError(f"Unknown FoodKeeper metric: {metric!r}")

    numbers = [v for v in (min_value, max_value) if _is_number(v)]
    if not numbers:
        return None
    low, high = min(numbers), max(numbers)
    factor = METRIC_DAYS[metric]
    return ShelfLifeDuration(min_days=math.floor(low * factor), max_days=math.floor(high * factor))


def _clean_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = " ".join(value.split())
    return text or None


def _parse_keywords(raw: Any) -> list[str]:
    seen: dict[str, None] = {}
    for part in str(raw or "").split(","):
        keyword = " ".join(part.split()).lower()
        if keyword:
            seen.setdefault(keyword, None)
    return list(seen)


def _best_duration(row: dict[str, Any], prefixes: Iterable[str]) -> ShelfLifeDuration | None:
    """First prefix with numeric days wins; otherwise the first with any note."""
    candidates = [
        parse_duration(row.get(f"{p}_Min"), row.get(f"{p}_Max"), row.get(f"{p}_Metric"))
        for p in prefixes
    ]
    found = [c for c in candidates if c is not None]
    for duration in found:
        if duration.min_days is not None:
            return duration
    return found[0] if found else None


def _tips(row: dict[str, Any]) -> dict[StorageKey, str]:
    tips: dict[StorageKey, list[str]] = {}
    for key, columns in TIP_COLUMNS.items():
        for column in columns:
            if text := _clean_text(row.get(column)):
                tips.setdefault(key, []).append(text)
    # A few rows put free text in a numeric Min column, e.g. "Or until best-by date."
    for key, prefixes in STORAGE_COLUMNS.items():
        for prefix in prefixes:
            if text := _clean_text(row.get(f"{prefix}_Min")):
                tips.setdefault(key, []).append(text)
    return {key: " ".join(dict.fromkeys(parts)) for key, parts in tips.items()}


def parse_product(row: dict[str, Any], source_categories: dict[int, str]) -> ShelfLifeProduct:
    category_id = int(row["Category_ID"])
    storage = {
        key: duration
        for key, prefixes in STORAGE_COLUMNS.items()
        if (duration := _best_duration(row, prefixes)) is not None
    }
    return ShelfLifeProduct(
        id=int(row["ID"]),
        category=CATEGORY_MAP.get(category_id, Category.OTHER),
        source_category=source_categories.get(category_id, "Unknown"),
        name=_clean_text(row["Name"]) or "",
        subtitle=_clean_text(row.get("Name_subtitle")),
        keywords=_parse_keywords(row.get("Keywords")),
        storage=storage,
        tips=_tips(row),
    )


def parse_products(doc: dict[str, Any]) -> list[ShelfLifeProduct]:
    source_categories = {
        int(r["ID"]): " / ".join(p for p in (r["Category_Name"], r["Subcategory_Name"]) if p)
        for r in sheet_rows(doc, "Category")
    }
    products = [parse_product(row, source_categories) for row in sheet_rows(doc, "Product")]
    return sorted(products, key=lambda p: p.id)


def data_version(doc: dict[str, Any]) -> dict[str, Any]:
    """The dataset's current version row, e.g. {"number": 128, "modified": "09-06-2018"}."""
    versions = sheet_rows(doc, "Version")
    current = next((v for v in versions if v.get("Current_Version") == "Yes"), versions[-1])
    return {"number": int(current["Data_Version_Number"]), "modified": current["Modified_Date"]}


def _min_days(products: Iterable[ShelfLifeProduct], key: StorageKey | None) -> list[int]:
    if key is None:
        return []
    return [
        d.min_days
        for p in products
        if (d := p.storage.get(key)) is not None and d.min_days is not None
    ]


def derive_category_defaults(products: list[ShelfLifeProduct]) -> list[CategoryDefault]:
    """Fallback days per (category, location, state): the low median of FoodKeeper minimums.

    Gaps are filled conservatively: perishable categories, or no pantry data, mean
    0 pantry days (don't leave out); no fridge/freezer data uses the all-products
    median. "other" uses all products. Leftovers use USDA's fixed guidance.
    """
    overall: dict[Location, int] = {
        loc: median_low(_min_days(products, keys[0])) for loc, keys in _LOCATION_KEYS.items()
    }
    defaults: list[CategoryDefault] = []
    for category in Category:
        if category is Category.OTHER:
            group = products
        else:
            group = [p for p in products if p.category is category]
        for location, (unopened_key, opened_key) in _LOCATION_KEYS.items():
            if category is Category.LEFTOVERS:
                unopened = opened = LEFTOVER_DEFAULTS[location]
            elif category in PERISHABLE_CATEGORIES and location is Location.PANTRY:
                unopened = opened = 0
            else:
                unopened_values = _min_days(group, unopened_key)
                if unopened_values:
                    unopened = median_low(unopened_values)
                else:
                    unopened = 0 if location is Location.PANTRY else overall[location]
                opened_values = _min_days(group, opened_key)
                opened = min(median_low(opened_values), unopened) if opened_values else unopened
            defaults.append(CategoryDefault(category=category, location=location, state=ItemState.UNOPENED, days=unopened))
            defaults.append(CategoryDefault(category=category, location=location, state=ItemState.OPENED, days=opened))
    return defaults
