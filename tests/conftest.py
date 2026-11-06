"""Shared pytest fixtures for isolated temporary SQLite databases."""

from __future__ import annotations

import json
import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest
from app.database import Base, create_db_engine, init_db
from app.seed import seed_database
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURE_DATA_DIR = REPO_ROOT / "data"


@pytest.fixture
def tmp_db_url(tmp_path: Path) -> str:
    """Return a file-backed SQLite URL under pytest's temporary directory."""
    db_path = tmp_path / "test.db"
    return f"sqlite:///{db_path}"


@pytest.fixture
def engine(tmp_db_url: str) -> Iterator[Engine]:
    """Create a fresh engine and schema for each test."""
    eng = create_db_engine(tmp_db_url)
    init_db(eng)
    try:
        yield eng
    finally:
        Base.metadata.drop_all(bind=eng)
        eng.dispose()


@pytest.fixture
def session(engine: Engine) -> Iterator[Session]:
    """Yield an ORM session bound to the temporary engine."""
    with Session(engine) as sess:
        yield sess


@pytest.fixture
def fixture_data_dir() -> Path:
    """Path to the committed seed JSON fixtures."""
    return FIXTURE_DATA_DIR


@pytest.fixture
def seeded_engine(tmp_db_url: str, fixture_data_dir: Path) -> Iterator[Engine]:
    """Seed a temporary database from the committed fixtures and yield its engine."""
    seed_database(database_url=tmp_db_url, data_dir=fixture_data_dir)
    eng = create_db_engine(tmp_db_url)
    try:
        yield eng
    finally:
        eng.dispose()


@pytest.fixture
def mutable_fixture_dir(tmp_path: Path, fixture_data_dir: Path) -> Path:
    """Copy committed fixtures into a writable temp directory for mutation tests."""
    dest = tmp_path / "fixtures"
    shutil.copytree(fixture_data_dir, dest)
    return dest


def read_json(path: Path) -> list[dict]:
    """Helper used by tests to load a fixture array."""
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: list[dict]) -> None:
    """Helper used by tests to rewrite a fixture array."""
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
