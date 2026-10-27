from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.normalize import normalize_name
from app.core.schemas import AliasOrigin
from app.core.shelf_life import ShelfLifeIndex
from app.db.models import CategoryDefaultRow, ShelfLifeAliasRow, ShelfLifeProductRow


def load_shelf_life_index(session: Session) -> ShelfLifeIndex:
    """Build the matcher from the seeded tables (products, defaults, all aliases)."""
    products = [row.to_schema() for row in session.scalars(select(ShelfLifeProductRow))]
    defaults = [row.to_schema() for row in session.scalars(select(CategoryDefaultRow))]
    aliases = {row.alias: row.product_id for row in session.scalars(select(ShelfLifeAliasRow))}
    return ShelfLifeIndex(products, defaults, aliases)


def learn_alias(session: Session, name: str, product_id: int) -> None:
    """Remember the user's chosen product for this name (overrides any curated alias)."""
    alias = normalize_name(name)
    if not alias:
        return
    session.merge(ShelfLifeAliasRow(alias=alias, product_id=product_id, origin=AliasOrigin.LEARNED))
