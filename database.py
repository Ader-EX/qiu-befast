from dotenv import load_dotenv
import os
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

# Load environment variables
load_dotenv()

# Read environment to determine which setup
ENV ="OFFICE"

print("======================================")
print("LOADING ENV : " , ENV)
print("======================================")

# Optional: load different dotenv file manually
# load_dotenv(".env.office") or load_dotenv(".env.home") depending on your context

# Build engine based on environment
if ENV == "OFFICE":
    DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./users.db")
    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
elif ENV == "HOME":
    DATABASE_URL = os.getenv("DATABASE_URL")
    engine = create_engine(DATABASE_URL)
else:
    raise ValueError("Invalid ENVIRONMENT_PROJECT value. Must be 'OFFICE' or 'HOME'.")

# Session and Base
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
