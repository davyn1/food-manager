import json
import shutil
from datetime import date
from pathlib import Path

import pytest

from app.core.shelf_life import ShelfLifeIndex
from app.db.migrate import upgrade_to_head
from app.db.seed import load_data_files, seed_reference_data
from app.db.session import make_engine, make_session_factory

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


class Clock:
    """A settable stand-in for date.today()."""

    def __init__(self, today: date) -> None:
        self.value = today

    def __call__(self) -> date:
        return self.value


@pytest.fixture(scope="session")
def real_index() -> ShelfLifeIndex:
    """Index over the committed FoodKeeper data and curated aliases."""
    shelf_life = json.loads((DATA_DIR / "shelf_life.json").read_text(encoding="utf-8"))
    aliases = json.loads((DATA_DIR / "aliases_extra.json").read_text(encoding="utf-8"))["aliases"]
    return ShelfLifeIndex.from_data(shelf_life, aliases)


@pytest.fixture(scope="session")
def seeded_db_template(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Migrate and seed once per test run."""
    path = tmp_path_factory.mktemp("template") / "seeded.db"
    url = f"sqlite:///{path.as_posix()}"
    upgrade_to_head(url)
    engine = make_engine(url)
    with make_session_factory(engine)() as session, session.begin():
        seed_reference_data(session, *load_data_files())
    engine.dispose()
    return path


@pytest.fixture
def seeded_db_copy(seeded_db_template: Path, tmp_path: Path) -> Path:
    """A private copy of the seeded database for one test."""
    path = tmp_path / "test.db"
    shutil.copy(seeded_db_template, path)
    return path
