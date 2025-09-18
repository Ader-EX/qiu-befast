from datetime import datetime

from pydantic import BaseModel
from typing import Optional, List
from schemas.CurrencySchemas import CurrencyOut


class CustomerBase(BaseModel):
    pass

class CustomerCreate(CustomerBase):
    name: str
    address: str
    kode_lambung: Optional[str] = None
    is_active: Optional[bool] = True
    currency_id: int
    created_at: datetime
    pass

class CustomerUpdate(CustomerBase):
    name: str
    address: str
    kode_lambung: Optional[str] = None
    is_active: Optional[bool] = True
    currency_id: int
    pass


class CustomerOut(CustomerBase):
    id:int
    code :str
    name: str
    address: str
    kode_lambung: Optional[str] = None
    is_active: Optional[bool] = True
    currency_id: int
    curr_rel: Optional[CurrencyOut] = None
    pass

    class Config:
        orm_mode = True
