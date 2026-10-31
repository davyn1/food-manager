import struct
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.web.templating import STATIC_DIR, STATIC_VERSION
from tests.conftest import make_app, signed_in_client


@pytest.fixture
def client(seeded_db_copy: Path) -> TestClient:
    """Signed out: the PWA files must work before anyone logs in."""
    return TestClient(make_app(seeded_db_copy), follow_redirects=False)


def png_size(data: bytes) -> tuple[int, int]:
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    return struct.unpack(">II", data[16:24])


def test_manifest_is_installable(client: TestClient) -> None:
    response = client.get("/manifest.webmanifest")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/manifest+json"
    manifest = response.json()
    assert manifest["display"] == "standalone"
    assert manifest["start_url"] == "/"
    assert manifest["name"] and manifest["short_name"]
    assert manifest["theme_color"].startswith("#")
    sizes = {(icon["sizes"], icon.get("purpose", "any")) for icon in manifest["icons"]}
    assert {("192x192", "any"), ("512x512", "any"), ("512x512", "maskable")} <= sizes


def test_manifest_icons_exist_with_declared_sizes(client: TestClient) -> None:
    for icon in client.get("/manifest.webmanifest").json()["icons"]:
        response = client.get(icon["src"])
        assert response.status_code == 200, icon["src"]
        width, height = png_size(response.content)
        assert f"{width}x{height}" == icon["sizes"]


def test_apple_touch_icon_is_opaque_180(client: TestClient) -> None:
    data = client.get("/static/icons/apple-touch-icon.png").content
    assert png_size(data) == (180, 180)


def test_service_worker_served_from_root_and_versioned(client: TestClient) -> None:
    response = client.get("/sw.js")
    assert response.status_code == 200
    assert "javascript" in response.headers["content-type"]
    assert response.headers["cache-control"] == "no-cache"
    assert "__VERSION__" not in response.text
    assert f'const VERSION = "{STATIC_VERSION}"' in response.text
    assert 'addEventListener("fetch"' in response.text


def test_service_worker_precache_urls_all_exist(client: TestClient) -> None:
    # A missing precache URL makes the service worker install fail entirely.
    script = client.get("/sw.js").text
    precache = script.split("const PRECACHE = [", 1)[1].split("];", 1)[0]
    urls = [
        line.strip().rstrip(",").replace('"', "").replace(" + VERSION", STATIC_VERSION).replace("OFFLINE_URL", "/offline")
        for line in precache.strip().splitlines()
    ]
    assert len(urls) == 6
    for url in urls:
        assert client.get(url).status_code == 200, url


def test_offline_page_needs_no_database(tmp_path: Path) -> None:
    app = create_app(f"sqlite:///{(tmp_path / 'fresh.db').as_posix()}")
    app.state.session_factory = None  # any DB access would now fail
    response = TestClient(app).get("/offline")
    assert response.status_code == 200
    assert "You're offline" in response.text


def test_pages_link_manifest_icons_and_versioned_assets(seeded_db_copy: Path) -> None:
    html = signed_in_client(make_app(seeded_db_copy)).get("/").text
    assert '<link rel="manifest" href="/manifest.webmanifest">' in html
    assert 'rel="apple-touch-icon"' in html
    assert 'name="apple-mobile-web-app-capable"' in html
    assert f"/static/app.css?v={STATIC_VERSION}" in html
    assert f"/static/app.js?v={STATIC_VERSION}" in html
    assert 'data-install="banner"' in html


def test_static_version_is_a_hash_of_the_cached_assets() -> None:
    import hashlib

    from app.web.templating import VERSIONED_ASSETS

    digest = hashlib.sha256()
    for name in VERSIONED_ASSETS:
        digest.update((STATIC_DIR / name).read_bytes())
    assert STATIC_VERSION == digest.hexdigest()[:10]


def test_head_requests_for_health_checks(client: TestClient) -> None:
    assert client.head("/health").status_code == 200
    assert client.head("/").status_code == 303  # signed out: redirect to login


def test_login_page_also_links_the_manifest(client: TestClient) -> None:
    # The installed app may open on the login page; it must still be installable.
    assert '<link rel="manifest"' in client.get("/login").text
