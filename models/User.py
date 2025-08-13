from datetime import datetime

from sqlalchemy import Column, Integer, String, Enum, DateTime, Boolean
from database import Base
import enum

from schemas.UserSchemas import UserType


class User(Base):
    __tablename__ = "users"
    id = Column(Integer,primary_key=True,index=True)
    username= Column(String(50), nullable=False, unique=True)
    password = Column(String(255), nullable=False)
    role = Column(Enum(UserType), default=UserType.MANAGER)
    is_active = Column(Boolean, default=True)
    last_login = Column(DateTime, default =datetime.now(), nullable=True)  # Store timestamp as an integer (e.g., Unix timestamp)