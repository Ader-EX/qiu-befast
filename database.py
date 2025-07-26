from dotenv import load_dotenv
import os
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

# Load environment variables
load_dotenv()

ENVIRONMENT_PROJECT = os.getenv("ENVIRONMENT_PROJECT", "HOME")
DATABASE_URL = os.getenv("DATABASE_URL")

print("======================================")
print("LOADING ENV:", ENVIRONMENT_PROJECT)
print("DATABASE_URL:", DATABASE_URL)
print("======================================")

if DATABASE_URL is None:
    raise ValueError("DATABASE_URL is not set in environment variables.")

# Handle SQLite special case
if DATABASE_URL.startswith("sqlite"):
    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
else:
    engine = create_engine(DATABASE_URL)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
