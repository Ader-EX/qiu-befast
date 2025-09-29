from datetime import date, datetime
from typing import Optional, List
from pydantic import BaseModel, Field

from schemas.ItemSchema import ItemBase
from schemas.PembayaranSchemas import WarehouseResponse


class StockAdjustmentItemCreate(BaseModel):
    item_id: int
    qty: int = Field(gt=0, description="Quantity must be greater than 0")
    adj_price: int = Field(ge=0, description="Adjustment price must be non-negative")


class StockAdjustmentItemResponse(BaseModel):
    id: int
    item_id: int
    qty: int
    adj_price: int
    stock_adjustment_id: int

    item_rel: Optional[ItemBase] = None

    class Config:
        from_attributes = True


class StockAdjustmentCreate(BaseModel):
    adjustment_type: str = Field(..., description="IN or OUT")
    adjustment_date: date
    warehouse_id: int
    stock_adjustment_items: List[StockAdjustmentItemCreate] = []


class StockAdjustmentUpdate(BaseModel):
    adjustment_type: Optional[str] = None
    adjustment_date: Optional[date] = None
    warehouse_id: Optional[int] = None
    stock_adjustment_items: Optional[List[StockAdjustmentItemCreate]] = None


class StockAdjustmentResponse(BaseModel):
    id: int
    no_adjustment: str
    adjustment_date: date
    adjustment_type: str
    status_adjustment: str
    warehouse_id: int
    created_at: datetime
    updated_at: Optional[datetime] = None
    deleted_at: Optional[datetime] = None
    is_deleted: Optional[bool] = None
    stock_adjustment_items: List[StockAdjustmentItemResponse] = []
    warehouse_rel: Optional[WarehouseResponse] = None



class StockAdjustmentListResponse(BaseModel):
    data: List[StockAdjustmentResponse]
    total: int
    skip: int
    limit: int

    class Config:
        from_attributes = True