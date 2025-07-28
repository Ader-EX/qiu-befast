from pydantic import BaseModel
from typing import Optional


class CustomerBase(BaseModel):
    name: str
    address: str
    is_active: Optional[bool] = True
    top_id: Optional[int] = None
    currency_id: Optional[int] = None


class CustomerCreate(CustomerBase):
    id: str  


class CustomerUpdate(CustomerBase):
    pass


class CustomerOut(CustomerBase):
    id: str

    class Config:
        orm_mode = True
