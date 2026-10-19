"""Database engine and session handling (SQLite via SQLAlchemy)."""

from collections.abc import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import settings

engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False} if settings.database_url.startswith("sqlite") else {},
)


@event.listens_for(engine, "connect")
def _sqlite_pragmas(dbapi_connection, _record) -> None:
    if settings.database_url.startswith("sqlite"):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()


SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def add_missing_columns() -> None:
    """Add columns that exist in the models but not yet in an existing database.

    `create_all` only creates missing tables. This keeps older OfficeHub databases working
    after an update without a migration tool. Only additive changes are supported.
    """
    from sqlalchemy import inspect

    inspector = inspect(engine)
    with engine.begin() as connection:
        for table in Base.metadata.sorted_tables:
            if not inspector.has_table(table.name):
                continue
            existing = {column["name"] for column in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name in existing:
                    continue
                # Names and types come from our own models, never from user input.
                ddl = f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {column.type.compile(engine.dialect)}'
                if column.server_default is not None:
                    ddl += f" DEFAULT {column.server_default.arg.text}"  # type: ignore[union-attr]
                connection.exec_driver_sql(ddl)
