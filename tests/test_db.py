from collections.abc import Iterator
from datetime import date
from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import Engine, inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import ROOT_DIR
from app.core.schemas import (
    AliasOrigin,
    Category,
    ExpirationSource,
    ItemEventType,
    ItemState,
    Location,
)
from app.core.shelf_life import MatchMethod, ShelfLifeIndex
from app.db.models import (
    Base,
    ItemEventRow,
    ItemRow,
    SettingRow,
    ShelfLifeAliasRow,
    ShelfLifeProductRow,
    StapleRow,
)
from app.db.seed import DEFAULT_STAPLES, load_data_files, seed_reference_data
from app.db.session import make_engine, make_session_factory
from app.db.shelf_life_repo import learn_alias, load_shelf_life_index
from app.services.users import UserService


def _alembic_config(url: str) -> Config:
    config = Config(str(ROOT_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT_DIR / "migrations"))
    config.set_main_option("sqlalchemy.url", url)
    return config


@pytest.fixture
def migrated_engine(tmp_path: Path) -> Iterator[Engine]:
    url = f"sqlite:///{(tmp_path / 'test.db').as_posix()}"
    command.upgrade(_alembic_config(url), "head")
    engine = make_engine(url)
    yield engine
    engine.dispose()


@pytest.fixture
def session(migrated_engine: Engine) -> Iterator[Session]:
    with make_session_factory(migrated_engine)() as s:
        yield s


@pytest.fixture(scope="module")
def data_files() -> tuple[dict, dict[str, int]]:
    return load_data_files()


# --- migrations -------------------------------------------------------------------

def test_migrations_match_models(migrated_engine: Engine) -> None:
    with migrated_engine.connect() as connection:
        diff = compare_metadata(MigrationContext.configure(connection), Base.metadata)
    assert diff == []


def test_migrations_downgrade_to_empty(tmp_path: Path) -> None:
    url = f"sqlite:///{(tmp_path / 'down.db').as_posix()}"
    config = _alembic_config(url)
    command.upgrade(config, "head")
    command.downgrade(config, "base")
    engine = make_engine(url)
    assert set(inspect(engine).get_table_names()) == {"alembic_version"}
    engine.dispose()


def _insert_item_sql() -> str:
    return (
        "INSERT INTO items (name, normalized_name, category, location, state, thawed, added_on, "
        "location_since, estimated_expires_on, expires_on, expiration_source, status, input_source) "
        "VALUES ('Milk', 'milk', 'dairy', 'fridge', 'unopened', 0, '2026-01-10', '2026-01-10', "
        "'2026-01-20', '2026-01-20', 'estimated', 'active', 'manual')"
    )


def test_owner_migration_gives_existing_items_to_first_user(tmp_path: Path) -> None:
    url = f"sqlite:///{(tmp_path / 'old.db').as_posix()}"
    config = _alembic_config(url)
    command.upgrade(config, "f432d1064dfa")  # users table exists, items have no owner yet
    engine = make_engine(url)
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "INSERT INTO users (username, password_hash, expiring_soon_days, created_at) "
            "VALUES ('first', 'x', 3, '2026-01-01'), ('second', 'x', 3, '2026-01-02')"
        )
        connection.exec_driver_sql(_insert_item_sql())
    command.upgrade(config, "head")
    with engine.connect() as connection:
        owners = connection.exec_driver_sql("SELECT owner_id FROM items").scalars().all()
        first_id = connection.exec_driver_sql("SELECT id FROM users WHERE username='first'").scalar()
    engine.dispose()
    assert owners == [first_id]


def test_owner_migration_refuses_items_without_any_user(tmp_path: Path) -> None:
    url = f"sqlite:///{(tmp_path / 'orphans.db').as_posix()}"
    config = _alembic_config(url)
    command.upgrade(config, "f432d1064dfa")
    engine = make_engine(url)
    with engine.begin() as connection:
        connection.exec_driver_sql(_insert_item_sql())
    engine.dispose()
    with pytest.raises(RuntimeError, match="no accounts"):
        command.upgrade(config, "head")


def test_foreign_keys_are_enforced(session: Session) -> None:
    session.add(ShelfLifeAliasRow(alias="ghost", product_id=999_999, origin=AliasOrigin.CURATED))
    with pytest.raises(IntegrityError):
        session.flush()


# --- seeding ----------------------------------------------------------------------

def test_seed_loads_reference_data(session: Session, data_files: tuple[dict, dict[str, int]]) -> None:
    report = seed_reference_data(session, *data_files)
    assert report.products == 661
    assert report.category_defaults == 90
    assert report.staples_added == len(DEFAULT_STAPLES)
    assert session.get(ShelfLifeProductRow, 118).name == "Chicken parts"


def test_seed_is_idempotent(session: Session, data_files: tuple[dict, dict[str, int]]) -> None:
    seed_reference_data(session, *data_files)
    second = seed_reference_data(session, *data_files)
    assert second.staples_added == 0
    assert second.settings_added == 0
    assert len(session.scalars(select(ShelfLifeProductRow.id)).all()) == 661
    assert len(session.scalars(select(StapleRow.id)).all()) == len(DEFAULT_STAPLES)


def test_reseed_keeps_user_staple_and_setting_edits(
    session: Session, data_files: tuple[dict, dict[str, int]], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.db.seed.DEFAULT_SETTINGS", {"example": "default"})
    seed_reference_data(session, *data_files)
    session.delete(session.scalars(select(StapleRow).where(StapleRow.name == "water")).one())
    session.get(SettingRow, "example").value = "changed"
    session.flush()

    seed_reference_data(session, *data_files)

    assert "water" not in session.scalars(select(StapleRow.name)).all()
    assert session.get(SettingRow, "example").value == "changed"


def test_learned_alias_survives_reseed_and_beats_curated(session: Session, data_files: tuple[dict, dict[str, int]]) -> None:
    seed_reference_data(session, *data_files)
    learn_alias(session, "Milk", 543)  # user prefers lactose-free
    session.flush()

    seed_reference_data(session, *data_files)

    row = session.get(ShelfLifeAliasRow, "milk")
    assert row.product_id == 543
    assert row.origin is AliasOrigin.LEARNED


# --- loading the matcher from the DB ----------------------------------------------

def test_index_from_db_matches_index_from_files(
    session: Session, data_files: tuple[dict, dict[str, int]], real_index: ShelfLifeIndex
) -> None:
    seed_reference_data(session, *data_files)
    db_index = load_shelf_life_index(session)
    for name in ("chicken thighs", "milk", "skim milk", "brocoli", "frozen peas", "xyz123"):
        assert db_index.match(name) == real_index.match(name), name
    assert db_index.product(27) == real_index.product(27)
    assert db_index.default_days(Category.MEAT, Location.PANTRY, ItemState.UNOPENED) == 0


def test_learned_alias_changes_matching(session: Session, data_files: tuple[dict, dict[str, int]]) -> None:
    seed_reference_data(session, *data_files)
    learn_alias(session, "Smoked Salmon", 167)
    session.flush()
    match = load_shelf_life_index(session).match("smoked salmon")
    assert match.method is MatchMethod.ALIAS
    assert match.product is not None and match.product.id == 167


# --- items ------------------------------------------------------------------------

def test_item_with_events_round_trips(session: Session, data_files: tuple[dict, dict[str, int]]) -> None:
    seed_reference_data(session, *data_files)
    owner = UserService(session).create_user("owner", "long-enough-pw")
    item = ItemRow(
        owner_id=owner.id,
        name="Chicken thighs", normalized_name="chicken thigh", shelf_life_id=118,
        category=Category.POULTRY, quantity=1.5, unit="lb", location=Location.FRIDGE,
        added_on=date(2026, 1, 10), location_since=date(2026, 1, 10),
        estimated_expires_on=date(2026, 1, 11), expires_on=date(2026, 1, 11),
        expiration_source=ExpirationSource.ESTIMATED,
    )
    item.events.append(ItemEventRow(type=ItemEventType.ADDED, to_location=Location.FRIDGE))
    session.add(item)
    session.commit()
    session.expunge_all()

    loaded = session.get(ItemRow, item.id)
    assert loaded.category is Category.POULTRY
    assert loaded.state is ItemState.UNOPENED
    assert loaded.thawed is False
    assert loaded.input_source == "manual"
    assert [e.type for e in loaded.events] == [ItemEventType.ADDED]
    assert loaded.events[0].occurred_at is not None


def test_deleting_item_deletes_its_events(session: Session, data_files: tuple[dict, dict[str, int]]) -> None:
    seed_reference_data(session, *data_files)
    owner = UserService(session).create_user("owner", "long-enough-pw")
    item = ItemRow(
        owner_id=owner.id,
        name="Milk", normalized_name="milk", category=Category.DAIRY, location=Location.FRIDGE,
        added_on=date(2026, 1, 10), location_since=date(2026, 1, 10),
        estimated_expires_on=date(2026, 1, 20), expires_on=date(2026, 1, 20),
        expiration_source=ExpirationSource.ESTIMATED,
    )
    item.events.append(ItemEventRow(type=ItemEventType.ADDED))
    session.add(item)
    session.commit()

    session.delete(item)
    session.commit()
    assert session.scalars(select(ItemEventRow)).all() == []
