import re
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.conftest import TEST_PASSWORD, create_user, make_app, sign_in_client, signed_in_client


@pytest.fixture
def app(seeded_db_copy: Path) -> FastAPI:
    return make_app(seeded_db_copy)


@pytest.fixture
def admin(app: FastAPI) -> TestClient:
    return signed_in_client(app, "davy", is_admin=True)


def new_invite_path(admin: TestClient) -> str:
    response = admin.post("/invites")
    assert response.status_code == 200
    match = re.search(r'value="http://testserver(/signup/[A-Za-z0-9_-]+)"', response.text)
    assert match, response.text
    return match.group(1)


def sign_up(app: FastAPI, path: str, username: str = "friend", password: str = "friend-password",
            confirm: str | None = None) -> tuple[TestClient, object]:
    client = TestClient(app, follow_redirects=False)
    response = client.post(path, data={"username": username, "password": password,
                                       "confirm": password if confirm is None else confirm})
    return client, response


# --- invites ------------------------------------------------------------------------

def test_admin_sees_invite_link_in_settings_others_do_not(app: FastAPI, admin: TestClient) -> None:
    assert 'href="/invites"' in admin.get("/settings").text
    friend = signed_in_client(app, "friend")
    assert 'href="/invites"' not in friend.get("/settings").text
    assert friend.get("/invites").status_code == 404
    assert friend.post("/invites").status_code == 404


def test_invite_link_creates_one_account_and_signs_in(app: FastAPI, admin: TestClient) -> None:
    path = new_invite_path(admin)
    assert "It's only shown now" in admin.post("/invites").text

    anon = TestClient(app, follow_redirects=False)
    assert "Create your account" in anon.get(path).text

    friend, response = sign_up(app, path)
    assert response.status_code == 303
    assert response.headers["location"] == "/"
    assert friend.get("/").status_code == 200  # signed in right away
    assert "No items here yet" in friend.get("/items").text

    page = admin.get("/invites").text
    assert "Used by friend" in page

    again = TestClient(app, follow_redirects=False)
    assert again.get(path).status_code == 404
    _, reuse = sign_up(app, path, username="someone")
    assert reuse.status_code == 404
    assert "not valid" in reuse.text


def test_signup_errors_keep_the_link_usable(app: FastAPI, admin: TestClient) -> None:
    path = new_invite_path(admin)
    _, mismatch = sign_up(app, path, confirm="different-password")
    assert mismatch.status_code == 422
    assert "match" in mismatch.text
    _, taken = sign_up(app, path, username="davy")
    assert taken.status_code == 422
    assert "is taken" in taken.text
    _, short = sign_up(app, path, password="short")
    assert short.status_code == 422
    _, ok = sign_up(app, path)
    assert ok.status_code == 303


def test_unknown_invite_link(app: FastAPI) -> None:
    response = TestClient(app, follow_redirects=False).get("/signup/not-a-real-token")
    assert response.status_code == 404
    assert "not valid" in response.text


def test_signed_in_user_is_asked_to_sign_out_first(app: FastAPI, admin: TestClient) -> None:
    path = new_invite_path(admin)
    assert "already signed in" in admin.get(path).text


def test_cancelled_invite_stops_working(app: FastAPI, admin: TestClient) -> None:
    path = new_invite_path(admin)
    invite_id = re.search(r'/invites/(\d+)/revoke', admin.get("/invites").text).group(1)
    assert admin.post(f"/invites/{invite_id}/revoke").status_code == 303
    assert TestClient(app).get(path).status_code == 404


# --- change password ----------------------------------------------------------------

def test_change_password_keeps_this_device_and_signs_out_others(app: FastAPI) -> None:
    phone = signed_in_client(app, "davy")
    laptop = sign_in_client(app, "davy")
    response = phone.post("/settings/password", data={
        "current": TEST_PASSWORD, "new": "brand-new-password", "confirm": "brand-new-password"})
    assert response.status_code == 303
    assert response.headers["location"] == "/settings?saved=password"
    assert "other devices are signed out" in phone.get("/settings?saved=password").text
    assert laptop.get("/").status_code == 303  # old session no longer valid
    sign_in_client(app, "davy", "brand-new-password")


@pytest.mark.parametrize(
    ("current", "new", "confirm", "message"),
    [
        ("wrong-password", "brand-new-password", "brand-new-password", "Current password is wrong"),
        (TEST_PASSWORD, "brand-new-password", "something-else", "match"),
        (TEST_PASSWORD, "short", "short", "at least 8"),
    ],
)
def test_change_password_errors(app: FastAPI, current: str, new: str, confirm: str, message: str) -> None:
    client = signed_in_client(app, "davy")
    response = client.post("/settings/password", data={"current": current, "new": new, "confirm": confirm})
    assert response.status_code == 422
    assert message in response.text
    assert client.get("/").status_code == 200  # still signed in


def test_admin_password_reset_signs_out(app: FastAPI) -> None:
    from app.services.users import UserService

    client = signed_in_client(app, "davy")
    with app.state.session_factory() as session, session.begin():
        UserService(session).set_password("davy", "reset-by-admin")
    assert client.get("/").status_code == 303


def test_signup_page_is_public_and_hides_tab_bar(app: FastAPI, admin: TestClient) -> None:
    page = TestClient(app).get(new_invite_path(admin)).text
    assert 'class="tabbar"' not in page
    assert '<meta name="referrer" content="same-origin">' in page


def test_existing_user_list_unaffected(app: FastAPI) -> None:
    create_user(app, "someone")
    assert TestClient(app).post("/login", data={"username": "someone", "password": TEST_PASSWORD},
                                follow_redirects=False).status_code == 303
