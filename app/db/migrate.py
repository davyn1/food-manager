from alembic import command
from alembic.config import Config

from app.config import ROOT_DIR


def alembic_config(url: str) -> Config:
    config = Config(str(ROOT_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT_DIR / "migrations"))
    config.set_main_option("sqlalchemy.url", url)
    return config


def upgrade_to_head(url: str) -> None:
    command.upgrade(alembic_config(url), "head")
