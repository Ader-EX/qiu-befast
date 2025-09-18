from datetime import datetime

from pydantic import BaseModel

from models.TermOfPayment import TermOfPayment
from schemas.CurrencySchemas import CurrencyOut
from schemas.TopSchemas import TopOut


class VendorBase(BaseModel):
    id: str
    name: str
    address: str
    currency_id: int
    top_id: int
    is_active: bool = True
    created_at: datetime

class VendorCreate(BaseModel):
    name: str
    address: str
    currency_id: int
    top_id: int
    is_active: bool = True
    pass

class VendorUpdate(VendorBase):
    pass

class VendorOut(VendorBase):
    top_rel : TopOut
    curr_rel : CurrencyOut
    pass

    class Config:
        from_attributes = True
