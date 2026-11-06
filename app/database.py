"""SQLite engine configuration with foreign-key enforcement."""

from __future__ import annotations

import os
from collections.abc import Generator
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

DEFAULT_DATABASE_URL = "sqlite:///./data/circles.db"


class Base(DeclarativeBase):
    """Shared declarative base for ORM models."""


def get_database_url(database_url: str | None = None) -> str:
    """Resolve the database URL from an argument or CIRCLES_DATABASE_URL."""
    return database_url or os.environ.get("CIRCLES_DATABASE_URL", DEFAULT_DATABASE_URL)


def _ensure_sqlite_parent_dir(url: str) -> None:
    """Create the parent directory for a file-backed SQLite URL when needed."""
    if not url.startswith("sqlite:///"):
        return
    # sqlite:///:memory: and sqlite:///file::memory:?cache=shared skip disk paths
    path_part = url.removeprefix("sqlite:///")
    if path_part in {":memory:", ""} or path_part.startswith("file:"):
        return
    Path(path_part).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)


@event.listens_for(Engine, "connect")
def _set_sqlite_pragma(dbapi_connection, connection_record) -> None:  # noqa: ARG001
    """Enable SQLite foreign-key enforcement on every new connection."""
    # Only apply to SQLite connections
    module_name = type(dbapi_connection).__module__
    if "sqlite" not in module_name:
        return
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def create_db_engine(database_url: str | None = None, *, echo: bool = False) -> Engine:
    """Create a SQLAlchemy engine for the configured SQLite database."""
    url = get_database_url(database_url)
    _ensure_sqlite_parent_dir(url)
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    return create_engine(url, echo=echo, future=True, connect_args=connect_args)


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Return a session factory bound to *engine*."""
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def get_session(engine: Engine) -> Generator[Session, None, None]:
    """Yield a session that commits on success and rolls back on error."""
    session = create_session_factory(engine)()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def init_db(engine: Engine) -> None:
    """Create all ORM tables if they do not already exist."""
    # Import models so metadata is populated before create_all.
    from app import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
