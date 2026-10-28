from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app


def test_health_returns_ok(seeded_db_copy: Path) -> None:
    client = TestClient(create_app(f"sqlite:///{seeded_db_copy.as_posix()}", auto_setup=False))

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_auto_setup_migrates_and_seeds_an_empty_database(tmp_path: Path) -> None:
    app = create_app(f"sqlite:///{(tmp_path / 'fresh.db').as_posix()}")
    assert app.state.index.match("chicken thighs").product is not None
