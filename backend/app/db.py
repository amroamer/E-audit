from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import settings

SCHEMAS = ("core", "recon")

engine = create_engine(settings.database_url, future=True, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


class Base(DeclarativeBase):
    pass


def create_schemas() -> None:
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
