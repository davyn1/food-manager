import re
from datetime import date, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.conftest import Clock, make_app, signed_in_client

D0 = date(2026, 1, 10)


@pytest.fixture
def clock() -> Clock:
    return Clock(D0)


@pytest.fixture
def client(seeded_db_copy: Path, clock: Clock) -> TestClient:
    return signed_in_client(make_app(seeded_db_copy, today=clock))


def add(client: TestClient, **fields: str) -> int:
    response = client.post("/items", data=fields)
    assert response.status_code == 303, response.text
    return int(re.search(r"item=(\d+)", response.headers["location"]).group(1))


# --- home and adding -------------------------------------------------------------

def test_home_renders_empty_state(client: TestClient) -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert "Nothing goes bad in the next 3 days" in response.text
    assert 'name="name"' in response.text
    assert "/static/vendor/htmx.min.js" in response.text


def test_quick_add_by_name_only_shows_on_home(client: TestClient) -> None:
    response = client.post("/items", data={"name": "chicken thighs"}, follow_redirects=True)
    assert response.status_code == 200
    assert "Added chicken thighs" in response.text
    assert "Expires tomorrow" in response.text  # in the expiring-soon list


def test_add_with_options(client: TestClient) -> None:
    item_id = add(client, name="Milk", quantity="1", unit="gal", location="fridge",
                  opened="1", user_expires_on="2026-01-20", category="dairy")
    page = client.get(f"/items/{item_id}").text
    assert "printed date" in page
    assert "1 gal" in page
    assert "Opened" in page


def test_add_blank_name_shows_error_and_keeps_input(client: TestClient) -> None:
    response = client.post("/items", data={"name": "  ", "quantity": "2"})
    assert response.status_code == 422
    assert "Please enter a name" in response.text
    assert 'value="2"' in response.text


def test_add_bad_number_shows_error(client: TestClient) -> None:
    response = client.post("/items", data={"name": "rice", "quantity": "lots"})
    assert response.status_code == 422
    assert "Please enter a number" in response.text


def test_preview_shows_match_and_estimate(client: TestClient) -> None:
    response = client.get("/add/preview", params={"name": "boneless chicken thighs"})
    assert response.status_code == 200
    assert "Chicken parts (legs or thighs)" in response.text
    assert "Fridge" in response.text
    assert "Expires tomorrow" in response.text


def test_preview_flags_and_blank(client: TestClient) -> None:
    assert "printed date" in client.get("/add/preview", params={"name": "milk"}).text
    assert client.get("/add/preview", params={"name": ""}).text == ""
    assert "No exact match" in client.get("/add/preview", params={"name": "zzzz"}).text


def test_preview_does_not_save(client: TestClient) -> None:
    client.get("/add/preview", params={"name": "milk"})
    assert "No items here yet" in client.get("/items").text


# --- lists -----------------------------------------------------------------------

def test_items_list_sorted_and_filtered(client: TestClient) -> None:
    add(client, name="rice")  # pantry, ~2 years
    add(client, name="chicken thighs")  # fridge, tomorrow
    page = client.get("/items").text
    assert page.index("chicken thighs") < page.index("rice")
    by_name = client.get("/items", params={"sort": "name"}).text
    assert by_name.index("chicken thighs") < by_name.index("rice")
    pantry_only = client.get("/items", params={"location": "pantry"}).text
    assert "rice" in pantry_only and "chicken thighs" not in pantry_only


def test_expired_list_and_badge(client: TestClient, clock: Clock) -> None:
    item_id = add(client, name="chicken thighs")
    clock.value = D0 + timedelta(days=3)
    expired = client.get("/expired").text
    assert "chicken thighs" in expired
    assert "Expired 2 days ago" in expired
    assert '<span class="badge" aria-label="1 expired">1</span>' in client.get("/").text
    client.post(f"/items/{item_id}/discard", data={"next": "/expired"})
    assert "Nothing has gone bad" in client.get("/expired").text


# --- item actions ----------------------------------------------------------------

def test_item_page_and_not_found(client: TestClient) -> None:
    item_id = add(client, name="chicken thighs")
    page = client.get(f"/items/{item_id}")
    assert page.status_code == 200
    assert "Chicken parts (legs or thighs)" in page.text
    assert client.get("/items/99999").status_code == 404


def test_move_open_and_date_actions(client: TestClient) -> None:
    item_id = add(client, name="chicken thighs")
    response = client.post(f"/items/{item_id}/move", data={"location": "freezer"})
    assert response.status_code == 303
    assert response.headers["location"] == f"/items/{item_id}"
    assert "9 months left" in client.get(f"/items/{item_id}").text  # 270 days

    client.post(f"/items/{item_id}/date", data={"user_expires_on": "2026-02-01"})
    assert "printed date" in client.get(f"/items/{item_id}").text
    client.post(f"/items/{item_id}/date", data={"clear": "1"})
    assert "estimated" in client.get(f"/items/{item_id}").text

    item_id = add(client, name="milk")
    client.post(f"/items/{item_id}/open")
    assert "Mark as opened" not in client.get(f"/items/{item_id}").text


def test_use_some_then_all(client: TestClient) -> None:
    item_id = add(client, name="rice", quantity="5", unit="lb")
    client.post(f"/items/{item_id}/use", data={"amount": "2"})
    assert "3 lb" in client.get(f"/items/{item_id}").text
    response = client.post(f"/items/{item_id}/used", data={"next": "/"}, follow_redirects=True)
    assert "Marked rice as used" in response.text
    assert "Used" in client.get(f"/items/{item_id}").text


def test_used_and_toss_can_be_undone(client: TestClient) -> None:
    item_id = add(client, name="milk")
    response = client.post(f"/items/{item_id}/used", data={"next": "/"}, follow_redirects=True)
    assert "Marked milk as used" in response.text
    assert f'action="/items/{item_id}/restore"' in response.text
    assert 'data-autohide="10"' in response.text

    undo = client.post(f"/items/{item_id}/restore", data={"next": "/"}, follow_redirects=True)
    assert "milk is back in your pantry" in undo.text
    assert "/restore" not in undo.text  # nothing left to undo
    assert "milk" in client.get("/items").text

    client.post(f"/items/{item_id}/discard", data={"next": "/expired"})
    assert "Threw out milk" in client.get(f"/expired?done=discarded&item={item_id}").text
    client.post(f"/items/{item_id}/restore")
    assert "Used it all" in client.get(f"/items/{item_id}").text


def test_added_notice_has_no_undo(client: TestClient) -> None:
    item_id = add(client, name="milk")
    page = client.get(f"/?done=added&item={item_id}").text
    assert "Added milk. Consider it remembered." in page
    assert "/restore" not in page
    assert 'data-autohide="4"' in page


def test_home_greets_by_name(client: TestClient) -> None:
    assert "Tester’s pantry" in client.get("/").text


def test_action_errors_render_on_item_page(client: TestClient) -> None:
    item_id = add(client, name="rice", quantity="5")
    response = client.post(f"/items/{item_id}/use", data={"amount": "-1"})
    assert response.status_code == 422
    assert "more than zero" in response.text
    client.post(f"/items/{item_id}/used")
    assert client.post(f"/items/{item_id}/open").status_code == 422
    assert client.post("/items/99999/open").status_code == 404


def test_change_match_page_and_learning(client: TestClient) -> None:
    item_id = add(client, name="smoked salmon")
    page = client.get(f"/items/{item_id}/match", params={"q": "smoked fish"}).text
    assert "cold smoked, vacuum pack" in page
    client.post(f"/items/{item_id}/match", data={"product_id": "167"})
    assert "21 days left" in client.get(f"/items/{item_id}").text
    preview = client.get("/add/preview", params={"name": "Smoked Salmon"}).text
    assert "cold smoked, vacuum pack" in preview


def test_change_match_to_none(client: TestClient) -> None:
    item_id = add(client, name="chicken thighs")
    client.post(f"/items/{item_id}/match", data={"product_id": ""})
    assert "None (Poultry defaults)" in client.get(f"/items/{item_id}").text


def test_next_parameter_cannot_leave_the_site(client: TestClient) -> None:
    item_id = add(client, name="milk")
    response = client.post(f"/items/{item_id}/used", data={"next": "//evil.example.com"})
    assert response.headers["location"].startswith(f"/items/{item_id}")


# --- settings --------------------------------------------------------------------

def test_settings_change_expiring_window(client: TestClient) -> None:
    add(client, name="apples")  # 21 days in the pantry
    assert "Nothing goes bad in the next 3 days" in client.get("/").text
    response = client.post("/settings", data={"expiring_soon_days": "30"}, follow_redirects=True)
    assert "Saved" in response.text
    home = client.get("/").text
    assert "next 30 days" in home and "apples" in home


def test_settings_rejects_bad_values(client: TestClient) -> None:
    for value in ("-1", "abc", "2.5", "100"):
        response = client.post("/settings", data={"expiring_soon_days": value})
        assert response.status_code == 422, value
