import os
import secrets
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
DEV_SECRET_FILE = DATA_DIR / ".secret_key"


def database_url() -> str:
    """SQLAlchemy URL; override with the FOOD_MANAGER_DATABASE_URL environment variable."""
    default = f"sqlite:///{(DATA_DIR / 'food_manager.db').as_posix()}"
    return os.environ.get("FOOD_MANAGER_DATABASE_URL", default)


def secret_key() -> str:
    """Key that signs the login cookie.

    Production sets FOOD_MANAGER_SECRET_KEY (a Fly secret). For local development a random
    key is created once in data/.secret_key (gitignored), so logins survive restarts.
    """
    if key := os.environ.get("FOOD_MANAGER_SECRET_KEY"):
        return key
    if DEV_SECRET_FILE.exists():
        return DEV_SECRET_FILE.read_text(encoding="utf-8").strip()
    key = secrets.token_urlsafe(48)
    DEV_SECRET_FILE.write_text(key, encoding="utf-8")
    return key


def secure_cookies() -> bool:
    """Send the login cookie over HTTPS only. On in production (FOOD_MANAGER_SECURE_COOKIES=1)."""
    return os.environ.get("FOOD_MANAGER_SECURE_COOKIES") == "1"
