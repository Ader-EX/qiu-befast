from pydantic import BaseModel
from typing import Optional

from schemas.CurrencySchemas import CurrencyOut
from schemas.TopSchemas import TopOut


class CustomerBase(BaseModel):
    id:str
    name: str
    address: str
    is_active: Optional[bool] = True
    top_id: int
    currency_id: int


class CustomerCreate(CustomerBase):
    id: str  


class CustomerUpdate(CustomerBase):
    pass


class CustomerOut(CustomerBase):
    curr_rel: Optional[CurrencyOut] = None
    top_rel: Optional[TopOut] = None
    pass

    class Config:
        orm_mode = True
