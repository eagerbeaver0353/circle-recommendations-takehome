"""FastAPI dependency wiring for request-scoped SQLAlchemy sessions."""

from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.database import create_db_engine, create_session_factory

# Process-level engine / session factory. Created once; not per request.
_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


def get_engine() -> Engine:
    """Return the shared application engine, creating it on first use."""
    global _engine, _session_factory
    if _engine is None:
        _engine = create_db_engine()
        _session_factory = create_session_factory(_engine)
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    """Return the shared session factory bound to the application engine."""
    get_engine()
    assert _session_factory is not None
    return _session_factory


def configure_engine(database_url: str | None = None, *, echo: bool = False) -> Engine:
    """Replace the shared engine (used by tests and application factories)."""
    global _engine, _session_factory
    if _engine is not None:
        _engine.dispose()
    _engine = create_db_engine(database_url, echo=echo)
    _session_factory = create_session_factory(_engine)
    return _engine


def reset_engine() -> None:
    """Dispose and clear the shared engine (test teardown helper)."""
    global _engine, _session_factory
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _session_factory = None


def get_db() -> Generator[Session, None, None]:
    """Yield a request-scoped Session that is always closed.

    Read-only recommendation requests do not commit. Callers that need writes
    must commit explicitly inside the request handler.
    """
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()


def check_database_ready(session: Session) -> bool:
    """Return True when a simple round-trip against the database succeeds."""
    try:
        session.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
