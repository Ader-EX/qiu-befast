from pydantic import BaseModel, Field, validator, field_validator
from typing import List, Optional
from datetime import datetime
from decimal import Decimal

from models.Pembelian import StatusPembelianEnum
from models.Penjualan import StatusPembayaranEnum, StatusPembelianEnum


# Base schemas
class PenjualanItemBase(BaseModel):
    item_id: Optional[int] = None
    qty: int
    discount: Decimal
    unit_price: Decimal
    tax_percentage : Optional[int] = 0

    @field_validator('qty')
    def validate_qty(cls, v):
        if v <= 0:
            raise ValueError('Quantity must be greater than 0')
        return v

    @field_validator('unit_price')
    def validate_unit_price(cls, v):
        if v < 0:
            raise ValueError('Unit price cannot be negative')
        return v

class PenjualanItemCreate(PenjualanItemBase):

    item_id: int
    pass

class PenjualanItemUpdate(PenjualanItemBase):
    item_id: int
    pass

class PenjualanItemResponse(BaseModel):
    id: int
    penjualan_id: int

    # Draft mode fields
    item_id: Optional[int] = None

    # Finalized mode fields
    item_name: Optional[str] = None
    item_sku: Optional[str] = None
    item_type: Optional[str] = None
    satuan_name: Optional[str] = None
    vendor_name: Optional[str] = None

    # Item details
    qty: int
    unit_price: Decimal
    discount: Decimal
    total_price: Decimal
    tax_percentage: Optional[int] = 0

    class Config:
        from_attributes = True

class AttachmentResponse(BaseModel):
    id: int
    filename: str
    file_size: Optional[int] = None
    mime_type: Optional[str] = None
    file_path: Optional[str] = None
    
    created_at: datetime

    class Config:
        from_attributes = True

class PenjualanBase(BaseModel):
    
    warehouse_id: Optional[int] = None
    customer_id: Optional[str] = None
    top_id: Optional[int] = None
    sales_date: Optional[datetime] = None
    sales_due_date: Optional[datetime] = None
    discount: Optional[Decimal] = Decimal('0.00')
    additional_discount: Optional[Decimal] = Decimal('0.00')
    expense: Optional[Decimal] = Decimal('0.00')

  

    @validator('discount', 'additional_discount', 'expense')
    def validate_amounts(cls, v):
        if v < 0:
            raise ValueError('Amount cannot be negative')
        return v
    
     
class PenjualanCreate(PenjualanBase):
    items: List[PenjualanItemCreate] = []

    @validator('items')
    def validate_items(cls, v):
        if not v:
            raise ValueError('At least one item is required')
        return v

class PenjualanUpdate(BaseModel):
    
    warehouse_id: Optional[int] = None
    customer_id: Optional[str] = None
    top_id: Optional[int] = None
    sales_date: Optional[datetime] = None
    sales_due_date: Optional[datetime] = None
    discount: Optional[Decimal] = None
    additional_discount: Optional[Decimal] = None
    expense: Optional[Decimal] = None
    items: Optional[List[PenjualanItemUpdate]] = None


    @validator('discount', 'additional_discount', 'expense')
    def validate_amounts(cls, v):
        if v is not None and v < 0:
            raise ValueError('Amount cannot be negative')
        return v

class PenjualanResponse(BaseModel):
    id: int
    no_penjualan: str
    status_pembayaran: StatusPembayaranEnum
    status_penjualan: StatusPembelianEnum

    sales_date: Optional[datetime] = None
    sales_due_date: Optional[datetime] = None

   
    additional_discount: Decimal
    expense: Decimal
    total_qty: int
    total_price: Decimal

    warehouse_id: Optional[int] = None
    customer_id: Optional[str] = None
    top_id: Optional[int] = None

    warehouse_name: Optional[str] = None
    customer_name: Optional[str] = None
    top_name: Optional[str] = None
    currency_name: Optional[str] = None

    items: List[PenjualanItemResponse] = Field(default_factory=list, alias="penjualan_items")
    attachments: List[AttachmentResponse] = Field(default_factory=list)

    class Config:
        from_attributes = True

class PenjualanStatusUpdate(BaseModel):
    status_Penjualan: Optional[StatusPembelianEnum] = None
    status_pembayaran: Optional[StatusPembayaranEnum] = None

class PenjualanListResponse(BaseModel):
    id: int
    no_penjualan: str
    status_pembayaran: StatusPembayaranEnum
    status_penjualan: StatusPembelianEnum
    sales_date: Optional[datetime] = None
    total_qty: int
    total_price: Decimal
    total_paid: Decimal
    total_return : Decimal


    # Customer info (draft or finalized)
    customer_name: Optional[str] = None

    # Warehouse info (draft or finalized)
    warehouse_name: Optional[str] = None

    # Item count
    items_count: Optional[int] = 0
    attachments_count: Optional[int] = 0

    class Config:
        from_attributes = True

# File upload response
class FileUploadResponse(BaseModel):
    filename: str
    size: Optional[int] = None
    type: str

class UploadResponse(BaseModel):
    message: str
    files: List[FileUploadResponse]

class ErrorResponse(BaseModel):
    detail: str
    error_code: Optional[str] = None

# Success response
class SuccessResponse(BaseModel):
    message: str
    data: Optional[dict] = None

# Totals calculation response
class TotalsResponse(BaseModel):
    subtotal_before_tax: Decimal
    subtotal_after_tax: Decimal
    tax_amount: Decimal
    discount_percent: Decimal     # keep the input % for reference
    discount_amount: Decimal
    additional_discount: Decimal
    expense: Decimal
    total_qty: int
    grand_total: Decimal  

    class Config:
        from_attributes = True