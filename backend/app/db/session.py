"""
DispatchResolve AI — Database Connection and Session Management.

Features:
- SQLite development and PostgreSQL production support
- SQLAlchemy 2.0 engine and session factory
- Safe database URL normalization
- Connection health checks
- Transaction commit/rollback helpers
- FastAPI request-scoped database sessions
- Connection pool configuration
- Explicit database lifecycle management

Security:
- Database credentials are never printed or logged.
- SQL statement echo is disabled.
- Failed transactions are rolled back.
- Database sessions are never shared across requests.
"""

from __future__ import annotations

import threading
from collections.abc import Generator, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from sqlalchemy import (
    Engine,
    create_engine,
    event,
    text,
)
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_ENGINE_LOCK = threading.Lock()

_engine: Engine | None = None

_session_factory: sessionmaker[Session] | None = None


# ============================================================
# DATABASE URL HELPERS
# ============================================================


def normalize_database_url(database_url: str) -> str:
    """
    Normalize supported SQLAlchemy database URLs.

    SQLite relative paths are resolved against the backend
    directory so application behavior does not depend on
    the shell's current working directory.
    """

    if not database_url.strip():
        raise ValueError("DATABASE_URL must not be empty.")

    url = make_url(database_url)

    if url.get_backend_name() == "sqlite":
        database = url.database

        if database in (None, "", ":memory:"):
            return database_url

        path = Path(database).expanduser()

        if not path.is_absolute():
            backend_root = Path(__file__).resolve().parents[2]
            path = backend_root / path

        path = path.resolve()

        return url.set(
            database=str(path),
        ).render_as_string(hide_password=False)

    if url.get_backend_name() == "postgresql":
        if url.drivername == "postgresql":
            return url.set(drivername="postgresql+psycopg").render_as_string(hide_password=False)

        return database_url

    raise ValueError("Unsupported database backend. Use SQLite or PostgreSQL.")


def database_backend(database_url: str) -> str:
    """Return the configured database backend name."""
    return make_url(database_url).get_backend_name()


# ============================================================
# ENGINE CREATION
# ============================================================


def build_engine(
    database_url: str,
    *,
    echo: bool = False,
    pool_size: int = 5,
    max_overflow: int = 10,
    pool_timeout: int = 30,
    pool_recycle: int = 1800,
) -> Engine:
    """
    Create a SQLAlchemy engine.

    For PostgreSQL:
    - Queue-based connection pooling
    - Pre-ping stale connections
    - Pool recycling
    - Connection timeout

    For SQLite:
    - Foreign keys enabled
    - Busy timeout configured
    - Connection arguments appropriate to local use
    """

    normalized_url = normalize_database_url(database_url)

    backend = database_backend(normalized_url)

    # SQL echo is deliberately disabled to prevent
    # accidental logging of sensitive query parameters.
    if echo:
        raise ValueError("SQL echo is disabled for security.")

    common_options: dict[str, Any] = {
        "echo": False,
        "future": True,
    }

    if backend == "sqlite":
        url = make_url(normalized_url)

        common_options["connect_args"] = {
            "check_same_thread": False,
            "timeout": 30,
        }

        if url.database == ":memory:":
            common_options["poolclass"] = StaticPool

        engine = create_engine(
            normalized_url,
            **common_options,
        )

        @event.listens_for(engine, "connect")
        def configure_sqlite_connection(
            dbapi_connection: Any,
            connection_record: Any,
        ) -> None:
            cursor = dbapi_connection.cursor()

            try:
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.execute("PRAGMA busy_timeout=30000")
            finally:
                cursor.close()

        return engine

    if backend == "postgresql":
        common_options.update(
            {
                "pool_pre_ping": True,
                "pool_size": pool_size,
                "max_overflow": max_overflow,
                "pool_timeout": pool_timeout,
                "pool_recycle": pool_recycle,
                "connect_args": {
                    "connect_timeout": 10,
                },
            }
        )

        return create_engine(
            normalized_url,
            **common_options,
        )

    raise ValueError("Unsupported database backend.")


# ============================================================
# GLOBAL ENGINE AND SESSION FACTORY
# ============================================================


def get_engine() -> Engine:
    """
    Return the process-local database engine.

    Engine initialization is lazy and thread-safe.
    """

    global _engine
    global _session_factory

    if _engine is not None:
        return _engine

    with _ENGINE_LOCK:
        if _engine is None:
            settings = get_settings()

            _engine = build_engine(
                settings.DATABASE_URL,
            )

            _session_factory = sessionmaker(
                bind=_engine,
                autoflush=False,
                expire_on_commit=False,
                class_=Session,
            )

            logger.info(
                "Database engine initialized: backend=%s",
                _engine.dialect.name,
            )

    return _engine


def get_session_factory() -> sessionmaker[Session]:
    """Return the configured SQLAlchemy session factory."""

    global _session_factory

    get_engine()

    if _session_factory is None:
        raise RuntimeError("Database session factory is unavailable.")

    return _session_factory


# ============================================================
# FASTAPI DATABASE DEPENDENCY
# ============================================================


def get_db() -> Generator[Session]:
    """
    Yield one SQLAlchemy session per FastAPI request.

    Write operations must explicitly commit in the
    service layer. Uncommitted changes are rolled back
    when the request session is closed.
    """

    factory = get_session_factory()

    with factory() as session:
        try:
            yield session
        except Exception:
            session.rollback()
            raise
        finally:
            session.rollback()


# ============================================================
# EXPLICIT TRANSACTION CONTEXT MANAGER
# ============================================================


@contextmanager
def transaction_scope() -> Iterator[Session]:
    """
    Provide an atomic database transaction.

    Commits on success and rolls back on failure.

    Suitable for scripts, background jobs and workers.
    """

    factory = get_session_factory()

    session = factory()

    try:
        yield session
        session.commit()

    except Exception:
        session.rollback()
        raise

    finally:
        session.close()


# ============================================================
# DATABASE HEALTH CHECKS
# ============================================================


def check_database_health(
    *,
    engine: Engine | None = None,
) -> dict[str, Any]:
    """
    Run a lightweight database connectivity check.

    Never include raw connection errors or database URLs
    in public health-check responses.
    """

    active_engine = engine or get_engine()

    try:
        with active_engine.connect() as connection:
            connection.execute(text("SELECT 1"))

        return {
            "status": "healthy",
            "database": active_engine.dialect.name,
        }

    except SQLAlchemyError:
        logger.warning("Database connectivity check failed.")

        return {
            "status": "unhealthy",
            "database": active_engine.dialect.name,
        }


# ============================================================
# DATABASE SHUTDOWN
# ============================================================


def dispose_database() -> None:
    """
    Release pooled database connections.

    Call during FastAPI lifespan shutdown.
    """

    global _engine
    global _session_factory

    with _ENGINE_LOCK:
        if _engine is not None:
            _engine.dispose()

            _engine = None
            _session_factory = None

            logger.info("Database connections disposed.")


# ============================================================
# TESTING UTILITIES
# ============================================================


def create_test_session_factory(
    database_url: str = "sqlite+pysqlite:///:memory:",
) -> tuple[Engine, sessionmaker[Session]]:
    """
    Create an isolated database engine and session factory.

    Intended for unit and integration tests.
    """

    engine = build_engine(database_url)

    factory = sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
        class_=Session,
    )

    return engine, factory


__all__ = [
    "normalize_database_url",
    "database_backend",
    "build_engine",
    "get_engine",
    "get_session_factory",
    "get_db",
    "transaction_scope",
    "check_database_health",
    "dispose_database",
    "create_test_session_factory",
]
