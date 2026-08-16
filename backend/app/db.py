"""Engine, session and schema bootstrap.

PostgreSQL is the target. SQLite is supported as a zero-infrastructure fallback so the
demo can be run without Docker: the two schemas become ATTACHed database files, which
makes every `core.*` / `recon.*` table name resolve unchanged. Nothing else in the
codebase needs to know which one is in use.
"""
from pathlib import Path

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import settings

SCHEMAS = ("core", "recon")

engine = create_engine(settings.database_url, future=True, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)

IS_SQLITE = engine.dialect.name == "sqlite"


class Base(DeclarativeBase):
    pass


if IS_SQLITE:
    # SQLite has no schemas; ATTACH one database file per schema, on every connection.
    _DIR = Path(engine.url.database or "eaudit.db").resolve().parent
    _DIR.mkdir(parents=True, exist_ok=True)

    @event.listens_for(engine, "connect")
    def _attach_schema_files(dbapi_conn, _record):  # pragma: no cover - driver hook
        cur = dbapi_conn.cursor()
        for s in SCHEMAS:
            cur.execute(f"ATTACH DATABASE '{_DIR / (s + '.db')}' AS {s}")
        cur.close()


def create_schemas() -> None:
    if IS_SQLITE:
        return  # the ATTACH above already made "core" and "recon" resolvable
    with engine.begin() as conn:
        for s in SCHEMAS:
            conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{s}"'))


def init_db() -> None:
    """Create schemas + tables. Demo bootstrap; production uses Alembic migrations."""
    create_schemas()
    from . import models  # noqa: F401  (register mappers on Base)

    Base.metadata.create_all(engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
