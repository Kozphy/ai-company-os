from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy.engine import Connection, Engine

from company_os.schema import control


def make_engine(url: str) -> Engine:
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
            cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.close()

    return engine


@contextmanager
def transaction(engine: Engine) -> Iterator[Connection]:
    """Serialize control mutations; no select-then-update claim race."""
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
    try:
        with engine.connect() as conn:
            revision = conn.exec_driver_sql("SELECT version_num FROM alembic_version").scalar_one()
            return revision == "0002" and conn.execute(sa.select(control.c.id)).scalar_one() == 1
    except sa.exc.SQLAlchemyError:
        return False
