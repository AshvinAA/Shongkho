import os
from dotenv import load_dotenv
from sqlalchemy import create_engine
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
    print("Database tables created successfully in TiDB Cloud!")