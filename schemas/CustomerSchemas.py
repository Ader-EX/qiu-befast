from pydantic import BaseModel
from typing import Optional, List
from schemas.CurrencySchemas import CurrencyOut


class CustomerBase(BaseModel):
    id:str
    name: str
    address: str
    kode_lambung: Optional[str] = None
    is_active: Optional[bool] = True
    currency_id: int

class CustomerCreate(CustomerBase):
    pass

class CustomerUpdate(CustomerBase):
    pass


class CustomerOut(CustomerBase):
    curr_rel: Optional[CurrencyOut] = None
    pass

    class Config:
        orm_mode = True
