from pydantic import BaseModel
import datetime


class TopCreate(BaseModel):
    name:str
    is_active:bool
    symbol:str

class TopUpdate(TopCreate):
    pass

class TopOut(TopCreate):
    id: int
    class Config:
         from_attributes = True