"""FastAPI dependency wiring for per-application SQLAlchemy resources."""

from __future__ import annotations

from collections.abc import Generator

from fastapi import Request
from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.database import create_db_engine, create_session_factory

# Tables required for the assessment schema to be considered initialized.
REQUIRED_TABLES: frozenset[str] = frozenset(
    {
        "topics",
        "users",
        "circles",
        "user_interests",
        "circle_tags",
        "memberships",
        "activity",
    }
)


def build_engine(database_url: str | None = None, *, echo: bool = False) -> Engine:
    """Create a SQLAlchemy engine for one application instance."""
    return create_db_engine(database_url, echo=echo)


def build_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Create a session factory bound to *engine*."""
    return create_session_factory(engine)


def get_db(request: Request) -> Generator[Session, None, None]:
    """Yield a request-scoped Session from the current application's factory.

    Read-only recommendation requests do not commit. Callers that need writes
    must commit explicitly inside the request handler. The session is always
    closed, including when the handler raises.
    """
    session_factory: sessionmaker[Session] = request.app.state.session_factory
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


def check_database_ready(session: Session) -> bool:
    """Return True when the DB is reachable and has the required schema.

    Performs a lightweight, read-only check. Does not create tables or seed
    data. An empty SQLite file without application tables is not ready.
    """
    try:
        session.execute(text("SELECT 1"))
        existing = set(inspect(session.get_bind()).get_table_names())
    except Exception:
        return False
    return REQUIRED_TABLES.issubset(existing)
