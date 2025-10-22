from datetime import datetime
from decimal import Decimal
from typing import List

from pydantic import BaseModel, Field, conint, condecimal

from models.InventoryLedger import SourceTypeEnum


class Movement(BaseModel):
    item_id: int
    trx_date: datetime
    order_key: str = Field(..., description="Deterministic order when timestamps tie")
    source_type: SourceTypeEnum
    source_id: str
    qty_in: conint(ge=0) = 0
    qty_out: conint(ge=0) = 0
    price_in: condecimal(max_digits=18, decimal_places=6) = Decimal("0")
    price_out: condecimal(max_digits=18, decimal_places=6) = Decimal("0")




class PostRequest(BaseModel):
    movements: List[Movement]


class ReportRow(BaseModel):
    item_name: str
qty_masuk: int
qty_keluar: int
qty_balance: int
harga_masuk: Decimal
harga_keluar: Decimal
hpp: Decimal




class ReportResponse(BaseModel):
    data: List[ReportRow]
    total: int


