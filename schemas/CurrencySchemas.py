from pydantic import BaseModel
from typing import Optional


class CurrencyBase(BaseModel):
    name: str
    symbol: str
    is_active: Optional[bool] = True


class CurrencyCreate(CurrencyBase):
    pass


class CurrencyUpdate(CurrencyBase):
    pass


class CurrencyOut(CurrencyBase):
    id: int

    class Config:
        orm_mode = True
