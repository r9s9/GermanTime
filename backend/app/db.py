"""Engine, session factory, and a tiny versioned migration runner."""

from collections.abc import Callable, Iterator

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from . import config


class Base(DeclarativeBase):
    pass


engine = create_engine(
    f"sqlite:///{config.DB_PATH}",
    connect_args={"check_same_thread": False},
)


@event.listens_for(engine, "connect")
def _sqlite_pragmas(dbapi_conn, _record):
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA synchronous=NORMAL")
    cur.execute("PRAGMA foreign_keys=ON")
    cur.close()


SessionLocal = sessionmaker(engine, expire_on_commit=False)

# Append-only: (version, migration). v1 is create_all; later entries mutate live DBs.
MIGRATIONS: list[tuple[int, Callable[[Session], None]]] = []


def init_db() -> None:
    config.ensure_dirs()
    from . import models  # noqa: F401  (register tables)

    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        db.execute(text("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)"))
        row = db.execute(text("SELECT version FROM schema_version")).fetchone()
        current = row[0] if row else 0
        if row is None:
            db.execute(text("INSERT INTO schema_version (version) VALUES (1)"))
        for version, migrate in MIGRATIONS:
            if version > current:
                migrate(db)
                db.execute(text("UPDATE schema_version SET version = :v"), {"v": version})
                current = version
        db.commit()

    from .services.seeds import load_seeds

    load_seeds()


def get_db() -> Iterator[Session]:
    with SessionLocal() as db:
        yield db
