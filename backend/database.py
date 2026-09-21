import os
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from models import Base

# 1. Load the hidden variables from your .env file
load_dotenv()

# 2. Get the TiDB URL
SQLALCHEMY_DATABASE_URL = os.getenv("TIDB_DATABASE_URL")

if not SQLALCHEMY_DATABASE_URL:
    raise ValueError("No database URL found! Check your .env file.")

# 3. Create the engine
# pool_pre_ping and pool_recycle are highly recommended for cloud databases 
# to prevent connections from timing out or dropping silently.
engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    pool_pre_ping=True,
    pool_recycle=3600
)

# 4. Set up the Session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# 5. Database connection helper for our web routes
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# 6. Function to build the tables in TiDB
def init_db():
    Base.metadata.create_all(bind=engine)
    _ensure_columns()
    print("Database tables created successfully in TiDB Cloud!")


def _ensure_columns():
    """Lightweight migration: add columns introduced after the first release
    (product pictures) to existing databases. Safe to run repeatedly.

    Runs the ALTER directly and treats 'duplicate column' errors as success,
    which works identically on TiDB/MySQL and SQLite."""
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
            except Exception as exc:  # noqa: BLE001 - migration best-effort
                conn.rollback()
                msg = str(exc).lower()
                if "duplicate" in msg or "already exists" in msg:
                    continue  # column is already there — expected on 2nd run
                print(f"[migration] skipped {table}.{column}: {exc}")