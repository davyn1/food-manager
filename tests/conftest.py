import json
import shutil
from collections.abc import Callable
from datetime import date
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.schemas import User
from app.core.shelf_life import ShelfLifeIndex
from app.main import create_app
from app.services.users import UserService
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


@pytest.fixture(autouse=True)
def fast_password_hashing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Real scrypt cost is deliberately slow; tests don't need it."""
    monkeypatch.setattr("app.core.passwords.SCRYPT_N", 2**10)


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


TEST_PASSWORD = "test-password-1"


def create_user(app: FastAPI, username: str, password: str = TEST_PASSWORD) -> User:
    with app.state.session_factory() as session, session.begin():
        return UserService(session).create_user(username, password)


def signed_in_client(app: FastAPI, username: str = "tester") -> TestClient:
    """A client for `app`, signed in as a newly created user. Doesn't follow redirects."""
    create_user(app, username)
    client = TestClient(app, follow_redirects=False)
    response = client.post("/login", data={"username": username, "password": TEST_PASSWORD})
    assert response.status_code == 303, response.text
    return client


def make_app(db_path: Path, today: Callable[[], date] = date.today) -> FastAPI:
    return create_app(f"sqlite:///{db_path.as_posix()}", today=today, auto_setup=False,
                      secret_key="test-secret", secure_cookies=False)
