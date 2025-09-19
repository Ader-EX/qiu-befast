from pydantic import BaseModel
from datetime import datetime


class TopCreate(BaseModel):
    name:str
    is_active:bool
    symbol:str


class TopUpdate(TopCreate):
    pass

class TopOut(TopCreate):
    id: int
    created_at: datetime
    class Config:
         from_attributes = True