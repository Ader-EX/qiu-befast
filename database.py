from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker



DATABASE_URL = "mysql+mysqlconnector://root:@localhost:3307/qiu_system"
# DATABASE_URL = "sqlite:///./users.db"
# engine = create_engine(DATABASE_URL, connect_args={
#     "check_same_thread" : False
# })

# SessionLocal  = sessionmaker(autocommit=False, bind=engine, autoflush=False)

engine = create_engine(DATABASE_URL)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

