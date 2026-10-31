from datetime import date, timedelta

import pytest

from app.web.templating import dot_level, dot_parts, expiry_text

TODAY = date(2026, 1, 10)


def on(days: int) -> date:
    return TODAY + timedelta(days=days)


@pytest.mark.parametrize(
    ("days", "parts"),
    [
        (0, ("today", "")),
        (1, ("1", "day")),
        (3, ("3", "days")),
        (59, ("59", "days")),
        (60, ("2", "mo")),
        (270, ("9", "mo")),
        (730, ("2", "yr")),
        (-1, ("−1", "day")),
        (-4, ("−4", "days")),
    ],
)
def test_dot_parts(days: int, parts: tuple[str, str]) -> None:
    assert dot_parts(on(days), TODAY) == parts


@pytest.mark.parametrize(
    ("days", "level"),
    [(-1, "expired"), (0, "now"), (1, "now"), (2, "soon"), (3, "soon"), (4, "ok"), (59, "ok"), (60, "later")],
)
def test_dot_level_with_three_day_window(days: int, level: str) -> None:
    assert dot_level(on(days), TODAY, soon_days=3) == level


def test_dot_level_follows_the_users_window() -> None:
    assert dot_level(on(6), TODAY, soon_days=7) == "soon"
    assert dot_level(on(6), TODAY, soon_days=3) == "ok"


@pytest.mark.parametrize(
    ("days", "text"),
    [(-3, "Expired 3 days ago"), (-1, "Expired yesterday"), (0, "Expires today"),
     (1, "Expires tomorrow"), (5, "5 days left"), (270, "9 months left"), (1000, "3 years left")],
)
def test_expiry_text(days: int, text: str) -> None:
    assert expiry_text(on(days), TODAY) == text


def test_pages_start_with_the_doctype(seeded_db_copy) -> None:
    from fastapi.testclient import TestClient

    from tests.conftest import make_app

    assert TestClient(make_app(seeded_db_copy)).get("/login").text.startswith("<!doctype html>")
