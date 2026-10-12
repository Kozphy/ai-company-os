"""SQLite and Postgres engine helpers for the local control database."""

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy.engine import Connection, Engine

from company_os.schema import control


def make_engine(url: str) -> Engine:
    """Open a SQLAlchemy engine and enable SQLite durability pragmas.

    File-backed SQLite URLs get their parent directory created. SQLite
    connections enable foreign keys and WAL. Other dialects are returned
    with pool pre-ping and no extra connection arguments.

    Args:
        url: SQLAlchemy database URL.

    Returns:
        An engine. The first real connection happens when a caller uses it.
    """
    if url.startswith("sqlite:///") and ":memory:" not in url:
        Path(url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
    engine = sa.create_engine(
        url,
        pool_pre_ping=True,
        connect_args={"check_same_thread": False, "timeout": 15} if url.startswith("sqlite") else {},
    )
    if engine.dialect.name == "sqlite":

        @sa.event.listens_for(engine, "connect")
        def pragma(dbapi_connection: object, connection_record: object) -> None:
            """Enable foreign keys and WAL on one SQLite connection.

            Args:
                dbapi_connection: DB-API connection created by SQLAlchemy.
                connection_record: SQLAlchemy pool record. Unused.
            """
            cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.close()

    return engine


@contextmanager
def transaction(engine: Engine) -> Iterator[Connection]:
    """Serialize control mutations so claims cannot race a select-then-update.

    SQLite takes an immediate lock. Other dialects lock the singleton control
    row with ``FOR UPDATE``. The transaction commits on success and rolls
    back on any exception, including ``BaseException``.

    Args:
        engine: Database engine.

    Yields:
        A connection inside the open transaction.
    """
    with engine.connect() as conn:
        try:
            if engine.dialect.name == "sqlite":
                conn.exec_driver_sql("BEGIN IMMEDIATE")
            else:
                conn.begin()
                conn.execute(sa.select(control).where(control.c.id == 1).with_for_update()).one()
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise


def ready(engine: Engine) -> bool:
    """Report whether revision ``0002`` and the control row are present.

    Args:
        engine: Database engine.

    Returns:
        ``True`` when Alembic is at ``0002`` and control id ``1`` exists.
        Database errors return ``False``.
    """
    try:
        with engine.connect() as conn:
            revision = conn.exec_driver_sql("SELECT version_num FROM alembic_version").scalar_one()
            return revision == "0002" and conn.execute(sa.select(control.c.id)).scalar_one() == 1
    except sa.exc.SQLAlchemyError:
        return False
