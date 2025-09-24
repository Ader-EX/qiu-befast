from datetime import datetime

from pydantic import BaseModel
from typing import Optional, List

from schemas.CurrencySchemas import CurrencyOut
from schemas.KodeLambungSchema import KodeLambungBase


class CustomerBase(BaseModel):
    pass

class CustomerCreate(CustomerBase):
    name: str
    address: str
    kode_lambungs : Optional[List[str]] = []
    is_active: Optional[bool] = True
    currency_id: int

    pass
class CustomerUpdate(CustomerBase):

    name: str
    address: str
    kode_lambungs : Optional[List[str]] = []
    is_active: Optional[bool] = True
    currency_id: int
    pass


class CustomerOut(CustomerBase):
    id:int
    code :str
    name: str
    address: str
    kode_lambung_rel : Optional[List[KodeLambungBase]] = []
    is_active: Optional[bool] = True
    currency_id: int
    curr_rel: Optional[CurrencyOut] = None
    created_at: datetime
    pass

    class Config:
        orm_mode = True
