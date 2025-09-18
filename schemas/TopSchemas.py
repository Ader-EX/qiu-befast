from pydantic import BaseModel
from datetime import datetime


class TopCreate(BaseModel):
    name:str
    is_active:bool
    symbol:str
    created_at: datetime

class TopUpdate(TopCreate):
    pass

class TopOut(TopCreate):
    id: int
    class Config:
         from_attributes = True