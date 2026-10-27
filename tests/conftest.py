import json
from pathlib import Path

import pytest

from app.core.shelf_life import ShelfLifeIndex

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


@pytest.fixture(scope="session")
def real_index() -> ShelfLifeIndex:
    """Index over the committed FoodKeeper data and curated aliases."""
    shelf_life = json.loads((DATA_DIR / "shelf_life.json").read_text(encoding="utf-8"))
    aliases = json.loads((DATA_DIR / "aliases_extra.json").read_text(encoding="utf-8"))["aliases"]
    return ShelfLifeIndex.from_data(shelf_life, aliases)
