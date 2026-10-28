"""PWA plumbing: web app manifest, service worker, offline page."""

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response

from app.web.templating import STATIC_DIR, STATIC_VERSION, templates

router = APIRouter()

THEME_COLOR = "#2f6f4e"
BACKGROUND_COLOR = "#f6f5f1"


def manifest() -> dict[str, Any]:
    return {
        "id": "/",
        "name": "Food Manager",
        "short_name": "Pantry",
        "description": "Track what's in your kitchen and use it before it expires.",
        "start_url": "/",
        "scope": "/",
        "display": "standalone",
        "orientation": "portrait",
        "theme_color": THEME_COLOR,
        "background_color": BACKGROUND_COLOR,
        "icons": [
            {"src": "/static/icons/icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any"},
            {"src": "/static/icons/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any"},
            {"src": "/static/icons/icon-maskable-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
        ],
        "shortcuts": [
            {"name": "Expired", "url": "/expired", "icons": [{"src": "/static/icons/icon-192.png", "sizes": "192x192"}]},
            {"name": "All items", "url": "/items", "icons": [{"src": "/static/icons/icon-192.png", "sizes": "192x192"}]},
        ],
    }


@router.get("/manifest.webmanifest", include_in_schema=False)
def web_manifest() -> JSONResponse:
    return JSONResponse(manifest(), media_type="application/manifest+json")


@router.get("/sw.js", include_in_schema=False)
def service_worker() -> Response:
    # Served from the root so it controls the whole site. Never cached by the browser,
    # so a new version (new STATIC_VERSION) is picked up on the next visit.
    script = (STATIC_DIR / "sw.js").read_text(encoding="utf-8").replace("__VERSION__", STATIC_VERSION)
    return Response(
        script,
        media_type="application/javascript",
        headers={"Cache-Control": "no-cache", "Service-Worker-Allowed": "/"},
    )


@router.get("/offline", include_in_schema=False, response_class=HTMLResponse)
def offline(request: Request) -> HTMLResponse:
    """Static page the service worker shows when there's no connection. No DB access."""
    return templates.TemplateResponse(request, "offline.html", {})
