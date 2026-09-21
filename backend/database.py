"""
Database bootstrap for the Shongkho backend.

Reads the connection URL from backend/.env (TIDB_DATABASE_URL) and exposes:
  - get_engine() / SessionLocal : SQLAlchemy engine + session factory
  - get_db()                    : FastAPI dependency (one session per request)
  - init_db()                   : creates missing tables + light migrations

TESTING NOTE:
  The URL is read lazily (inside get_engine) rather than at import time so
  the test suite can point the app at a throwaway SQLite database before
  the first request — no production credentials are needed for tests.
"""
import os

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

import models

# Absolute path of this file's folder — .env lives next to it.
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# 1. Load backend/.env if present. The explicit path keeps behaviour
#    identical no matter which directory uvicorn/pytest was launched from.
load_dotenv(os.path.join(BASE_DIR, ".env"))

# 2. Module-level cache so repeated imports share one engine.
_engine = None
_SessionLocal = None


def get_database_url() -> str:
    """
    Return the configured database URL.

    Resolution order:
      1. SQLALCHEMY_DATABASE_URL / TIDB_DATABASE_URL from the environment
         (this is how the test suite injects its SQLite URL).
      2. TIDB_DATABASE_URL from backend/.env (normal production path).

    Raises a clear error when neither is set, instead of failing later
    with a confusing "could not connect" message.
    """
    url = os.getenv("SQLALCHEMY_DATABASE_URL") or os.getenv("TIDB_DATABASE_URL")
    if not url:
        raise ValueError(
            "No database URL configured. Set TIDB_DATABASE_URL in backend/.env "
            "(or SQLALCHEMY_DATABASE_URL in the environment)."
        )

    # A RELATIVE SQLite path (e.g. sqlite:///./Shongkho_test.db) is resolved
    # against the process's CURRENT WORKING DIRECTORY. That made the app's
    # database depend on where uvicorn was launched from (project root vs
    # backend/): accounts seeded from one directory "vanished" when the
    # server started from the other. Anchor every relative sqlite path to
    # backend/ (this file's folder) so one .env always means one database.
    if url.startswith("sqlite:///"):
        path_part = url[len("sqlite:///"):].split("?")[0]  # drop query params
        is_memory = path_part in ("", ":memory:")          # never rewrite these
        if not is_memory and not os.path.isabs(path_part):
            absolute = os.path.normpath(os.path.join(BASE_DIR, path_part))
            # THREE slashes: "sqlite:///<path>". SQLAlchemy needs exactly three
            # for a Windows drive path ("sqlite://F:/x" would parse 'F:' as a
            # host with an empty port and crash with int('')). On POSIX the
            # leading "/" of an absolute path makes it four — also correct.
            url = "sqlite:///" + absolute.replace(os.sep, "/")
    return url


def get_engine():
    """
    Create (once) and return the SQLAlchemy engine.

    pool_pre_ping / pool_recycle matter for cloud databases (TiDB) where
    idle connections are dropped silently; they are harmless for SQLite.
    """
    global _engine
    if _engine is None:
        _engine = create_engine(
            get_database_url(),
            pool_pre_ping=True,
            pool_recycle=3600,
        )
    return _engine


def get_session_factory():
    """Create (once) and return the session factory bound to our engine."""
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(
            autocommit=False,
            autoflush=False,
            bind=get_engine(),
        )
    return _SessionLocal


def get_db():
    """
    FastAPI dependency: one session per request, always closed.

    The test suite overrides this dependency with its own in-memory
    SQLite session (see backend/tests/conftest.py).
    """
    db = get_session_factory()()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Create any missing tables and run lightweight column migrations."""
    engine = get_engine()
    models.Base.metadata.create_all(bind=engine)
    _ensure_columns(engine)
    print("Database tables created successfully!")


def _ensure_columns(engine):
    """
    Lightweight migration: adds columns introduced after the first release
    (e.g. product pictures) to databases created earlier. Safe to run on
    every boot — 'duplicate column' errors are treated as success, which
    works identically on TiDB/MySQL and SQLite.
    """
    migrations = [
        # (table, column, DDL)
        ("products", "photo", "ALTER TABLE products ADD COLUMN photo VARCHAR(550)"),
    ]
    with engine.connect() as conn:
        for table, column, ddl in migrations:
            try:
                conn.execute(text(ddl))
                conn.commit()
                print(f"[migration] added column {table}.{column}")
            except Exception as exc:  # noqa: BLE001 - migration is best-effort
                conn.rollback()
                msg = str(exc).lower()
                if "duplicate" in msg or "already exists" in msg:
                    continue  # column already there — expected from 2nd run on
                print(f"[migration] skipped {table}.{column}: {exc}")
