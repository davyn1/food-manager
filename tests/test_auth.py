from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.throttle import LoginThrottle
from app.db.models import UserRow
from tests.conftest import TEST_PASSWORD, create_user, make_app, signed_in_client


@pytest.fixture
def app(seeded_db_copy: Path) -> FastAPI:
    return make_app(seeded_db_copy)


@pytest.fixture
def anon(app: FastAPI) -> TestClient:
    return TestClient(app, follow_redirects=False)


@pytest.mark.parametrize("path", ["/", "/items", "/expired", "/settings", "/items/1", "/add/preview?name=milk"])
def test_pages_redirect_to_login_when_signed_out(anon: TestClient, path: str) -> None:
    response = anon.get(path)
    assert response.status_code == 303
    assert response.headers["location"].startswith("/login")


def test_redirect_keeps_where_you_were_going(anon: TestClient) -> None:
    assert anon.get("/items?location=fridge").headers["location"] == "/login?next=%2Fitems%3Flocation%3Dfridge"
    assert anon.get("/").headers["location"] == "/login"


def test_actions_are_blocked_when_signed_out(anon: TestClient) -> None:
    assert anon.post("/items", data={"name": "milk"}).status_code == 303
    assert anon.post("/settings", data={"expiring_soon_days": "5"}).status_code == 303


@pytest.mark.parametrize("path", ["/login", "/health", "/manifest.webmanifest", "/sw.js", "/offline",
                                  "/static/app.css", "/static/icons/icon-192.png"])
def test_public_paths_work_signed_out(anon: TestClient, path: str) -> None:
    assert anon.get(path).status_code == 200


def test_login_success_goes_to_next(app: FastAPI, anon: TestClient) -> None:
    create_user(app, "davy")
    response = anon.post("/login", data={"username": "Davy", "password": TEST_PASSWORD, "next": "/expired"})
    assert response.status_code == 303
    assert response.headers["location"] == "/expired"
    assert anon.get("/expired").status_code == 200


def test_login_rejects_offsite_next(app: FastAPI, anon: TestClient) -> None:
    create_user(app, "davy")
    response = anon.post("/login", data={"username": "davy", "password": TEST_PASSWORD,
                                         "next": "//evil.example.com"})
    assert response.headers["location"] == "/"


def test_wrong_password_shows_error(app: FastAPI, anon: TestClient) -> None:
    create_user(app, "davy")
    response = anon.post("/login", data={"username": "davy", "password": "wrong-password"})
    assert response.status_code == 422
    assert "Wrong username or password" in response.text
    assert 'value="davy"' in response.text
    assert anon.get("/").status_code == 303


def test_unknown_user_gets_the_same_error(anon: TestClient) -> None:
    response = anon.post("/login", data={"username": "nobody", "password": "whatever-pw"})
    assert response.status_code == 422
    assert "Wrong username or password" in response.text


def test_login_locks_after_repeated_failures(app: FastAPI, anon: TestClient) -> None:
    app.state.login_throttle = LoginThrottle(max_failures=2)
    create_user(app, "davy")
    for _ in range(2):
        anon.post("/login", data={"username": "davy", "password": "wrong-password"})
    response = anon.post("/login", data={"username": "davy", "password": TEST_PASSWORD})
    assert response.status_code == 422
    assert "Too many attempts" in response.text


def test_login_page_redirects_when_already_signed_in(app: FastAPI) -> None:
    client = signed_in_client(app)
    assert client.get("/login").status_code == 303


def test_logout(app: FastAPI) -> None:
    client = signed_in_client(app)
    assert "Signed in as" in client.get("/settings").text
    response = client.post("/logout")
    assert response.headers["location"] == "/login"
    assert client.get("/").status_code == 303


def test_deleted_user_is_signed_out(app: FastAPI) -> None:
    client = signed_in_client(app, "temp")
    with app.state.session_factory() as session, session.begin():
        session.query(UserRow).delete()
    assert client.get("/").status_code == 303


def test_tampered_cookie_is_rejected(app: FastAPI) -> None:
    client = signed_in_client(app)
    cookie = client.cookies.get("pantry_session")
    client.cookies.set("pantry_session", cookie[:-4] + "AAAA")
    assert client.get("/").status_code == 303


def test_cookie_flags(seeded_db_copy: Path) -> None:
    app = make_app(seeded_db_copy)
    create_user(app, "davy")
    response = TestClient(app).post("/login", data={"username": "davy", "password": TEST_PASSWORD},
                                    follow_redirects=False)
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie
    assert "samesite=lax" in cookie
    assert "secure" not in cookie  # local http


def test_secure_cookie_in_production_mode(seeded_db_copy: Path) -> None:
    from app.main import create_app

    app = create_app(f"sqlite:///{seeded_db_copy.as_posix()}", auto_setup=False,
                     secret_key="k", secure_cookies=True)
    create_user(app, "davy")
    response = TestClient(app, base_url="https://testserver").post(
        "/login", data={"username": "davy", "password": TEST_PASSWORD}, follow_redirects=False)
    assert "secure" in response.headers["set-cookie"].lower()


def test_two_users_have_separate_pantries(app: FastAPI) -> None:
    davy = signed_in_client(app, "davy")
    friend = signed_in_client(app, "friend")
    response = davy.post("/items", data={"name": "chicken thighs"})
    item_url = "/items/" + response.headers["location"].split("item=")[1]

    assert "chicken thighs" in davy.get("/items").text
    assert "chicken thighs" not in friend.get("/items").text
    assert friend.get(item_url).status_code == 404
    assert friend.post(item_url + "/used").status_code == 404
    assert "Expires tomorrow" in davy.get(item_url).text


def test_signed_out_pages_hide_the_tab_bar(anon: TestClient) -> None:
    assert 'class="tabbar"' not in anon.get("/login").text
