from datetime import datetime
from typing import Optional

from pydantic import BaseModel
import enum

class UserType(enum.Enum):
    OWNER = 0
    MANAGER = 1
    STAFF =2
    ALL = 3

class UserCreate(BaseModel):
    username:str
    password:str
    is_active:bool = True
    role: UserType = UserType.STAFF


class RequestDetails(BaseModel):
    username:str
    password:str

class TokenSchema(BaseModel):
    access_token: str
    refresh_token: str

class changepassword(BaseModel):
    email:str
    old_password:str
    new_password:str

class TokenCreate(BaseModel):
    user_id:str
    access_token:str
    refresh_token:str
    status:bool
    created_date:datetime


class UserOut(BaseModel):
    id: int
    username: str
    role: UserType
    is_active : bool
    last_login: Optional[datetime] = None

    class Config:
        from_attributes = True


class UserUpdate(BaseModel):
    username: Optional[str] = None
    password: Optional[str] = None
    role: Optional[UserType] = None
