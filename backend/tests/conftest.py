"""Shared pytest fixtures: each test gets a fresh throwaway SQLite DB."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # backend/ on path for `import app`

import pytest


@pytest.fixture()
def db_session(tmp_path, monkeypatch):
    # Nuke the entire app.* module tree so config/db/models/services all
    # reimport fresh and bind to this test's isolated DB path. Deleting only
    # `app.db`/`app.models` from sys.modules is NOT enough: `from . import
    # models` resolves via getattr(app_package, "models") before consulting
    # sys.modules, so the stale module (bound to a stale, empty Base.metadata)
    # would still be picked up and create_all() would create zero tables.
    for name in [m for m in list(sys.modules) if m == "app" or m.startswith("app.")]:
        del sys.modules[name]

    from app import config

    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.db")

    from app.db import SessionLocal, init_db

    init_db()
    with SessionLocal() as session:
        yield session
