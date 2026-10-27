from typing import Any

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.config import database_url


def make_engine(url: str | None = None) -> Engine:
    url = url or database_url()
    connect_args: dict[str, Any] = {}
    if url.startswith("sqlite"):
        # FastAPI may use a connection from a different thread than the one that opened it.
        connect_args["check_same_thread"] = False
    engine = create_engine(url, connect_args=connect_args)

    if engine.dialect.name == "sqlite":
        @event.listens_for(engine, "connect")
        def _enable_foreign_keys(dbapi_connection: Any, _record: Any) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(engine, expire_on_commit=False)
