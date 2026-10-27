import os
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"


def database_url() -> str:
    """SQLAlchemy URL; override with the FOOD_MANAGER_DATABASE_URL environment variable."""
    default = f"sqlite:///{(DATA_DIR / 'food_manager.db').as_posix()}"
    return os.environ.get("FOOD_MANAGER_DATABASE_URL", default)
