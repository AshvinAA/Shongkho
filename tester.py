from database import engine, init_db
from models import Base

def reset_database():
    print("Dropping old tables...")
    Base.metadata.drop_all(bind=engine)
    
    print("Creating updated tables from models.py...")
    init_db()
    print("Database reset successfully!")

if __name__ == "__main__":
    reset_database()