"""Load reference data into the database. Safe to run repeatedly.

- Shelf-life products and category defaults: upserted from data/shelf_life.json.
- Curated aliases: replaced from data/aliases_extra.json; aliases learned from the user's
  corrections are kept and win over a curated alias with the same name.
- Staples and settings: defaults inserted only when missing, so user edits survive.

Usage (after `alembic upgrade head`):
    python -m app.db.seed
"""

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.config import DATA_DIR
from app.core.normalize import normalize_name
from app.core.schemas import AliasOrigin, CategoryDefault, ShelfLifeProduct
from app.db.models import (
    CategoryDefaultRow,
    SettingRow,
    ShelfLifeAliasRow,
    ShelfLifeProductRow,
    StapleRow,
)

DEFAULT_STAPLES: tuple[str, ...] = ("salt", "pepper", "oil", "water", "sugar", "flour")
# App-wide settings. Per-person settings (like the expiring-soon window) live on users.
DEFAULT_SETTINGS: dict[str, str] = {}


@dataclass(frozen=True)
class SeedReport:
    products: int
    category_defaults: int
    curated_aliases: int
    staples_added: int
    settings_added: int


def load_data_files(data_dir: Path = DATA_DIR) -> tuple[dict[str, Any], dict[str, int]]:
    shelf_life = json.loads((data_dir / "shelf_life.json").read_text(encoding="utf-8"))
    aliases = json.loads((data_dir / "aliases_extra.json").read_text(encoding="utf-8"))["aliases"]
    return shelf_life, aliases


def seed_reference_data(
    session: Session, shelf_life: Mapping[str, Any], aliases: Mapping[str, int]
) -> SeedReport:
    products = [ShelfLifeProduct.model_validate(p) for p in shelf_life["products"]]
    for product in products:
        json_fields = product.model_dump(mode="json", include={"storage", "tips"})
        session.merge(
            ShelfLifeProductRow(
                id=product.id,
                category=product.category,
                source_category=product.source_category,
                name=product.name,
                subtitle=product.subtitle,
                keywords=list(product.keywords),
                storage=json_fields["storage"],
                tips=json_fields["tips"],
            )
        )

    defaults = [CategoryDefault.model_validate(d) for d in shelf_life["category_defaults"]]
    for default in defaults:
        session.merge(CategoryDefaultRow(**default.model_dump()))
    session.flush()

    session.execute(delete(ShelfLifeAliasRow).where(ShelfLifeAliasRow.origin == AliasOrigin.CURATED))
    learned = set(session.scalars(select(ShelfLifeAliasRow.alias)))
    curated = {normalize_name(alias): product_id for alias, product_id in aliases.items()}
    for alias, product_id in curated.items():
        if alias not in learned:
            session.add(ShelfLifeAliasRow(alias=alias, product_id=product_id, origin=AliasOrigin.CURATED))

    staples_added = 0
    if session.scalar(select(StapleRow.id).limit(1)) is None:
        for name in DEFAULT_STAPLES:
            session.add(StapleRow(name=normalize_name(name)))
        staples_added = len(DEFAULT_STAPLES)

    existing_settings = set(session.scalars(select(SettingRow.key)))
    settings_added = 0
    for key, value in DEFAULT_SETTINGS.items():
        if key not in existing_settings:
            session.add(SettingRow(key=key, value=value))
            settings_added += 1

    session.flush()
    return SeedReport(
        products=len(products),
        category_defaults=len(defaults),
        curated_aliases=len(curated.keys() - learned),
        staples_added=staples_added,
        settings_added=settings_added,
    )


def main() -> None:
    from app.db.session import make_engine, make_session_factory

    engine = make_engine()
    shelf_life, aliases = load_data_files()
    with make_session_factory(engine)() as session, session.begin():
        report = seed_reference_data(session, shelf_life, aliases)
    print(f"Seeded {engine.url}: {report}")


if __name__ == "__main__":
    main()
