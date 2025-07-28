from sqlalchemy import Column,Integer, String, Enum
from database import Base
import enum

class UserType(enum.Enum):
    ADMIN = 0
    MANAGER = 1

class User(Base):
    __tablename__ = "users"
    id = Column(Integer,primary_key=True,index=True)
    username= Column(String(50), nullable=False, unique=True)
    password = Column(String(255), nullable=False)
    role = Column(Enum(UserType), default=UserType.ADMIN)