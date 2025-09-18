from datetime import datetime

from pydantic import BaseModel
from typing import Optional


class WarehouseBase(BaseModel):
    name: str
    address: str
    is_active: Optional[bool]
    created_at: datetime


class WarehouseCreate(WarehouseBase):
    pass


class WarehouseUpdate(WarehouseBase):
    pass


class WarehouseOut(WarehouseBase):
    id: int

    class Config:
        orm_mode = True
