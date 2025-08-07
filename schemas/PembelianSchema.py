from pydantic import BaseModel, Field, validator, field_validator
from typing import List, Optional
from datetime import datetime
from decimal import Decimal
from enum import Enum

from models.Pembelian import StatusPembayaranEnum, StatusPembelianEnum


# Base schemas
class PembelianItemBase(BaseModel):
    item_id: Optional[int] = None
    qty: int
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

class PembelianItemCreate(PembelianItemBase):
    pass

class PembelianItemUpdate(PembelianItemBase):
    pass

class PembelianItemResponse(BaseModel):
    id: int
    pembelian_id: int

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

class PembelianBase(BaseModel):
    no_pembelian: str
    warehouse_id: Optional[int] = None
    customer_id: Optional[str] = None
    top_id: Optional[int] = None
    sales_date: Optional[datetime] = None
    sales_due_date: Optional[datetime] = None
    discount: Optional[Decimal] = Decimal('0.00')
    additional_discount: Optional[Decimal] = Decimal('0.00')
    tax : Optional[int] = 0
    expense: Optional[Decimal] = Decimal('0.00')

    @validator('no_pembelian')
    def validate_no_pembelian(cls, v):
        if not v or v.strip() == "":
            raise ValueError('No pembelian cannot be empty')
        return v.strip()

    @validator('discount', 'additional_discount', 'expense')
    def validate_amounts(cls, v):
        if v < 0:
            raise ValueError('Amount cannot be negative')
        return v

class PembelianCreate(PembelianBase):
    items: List[PembelianItemCreate] = []

    @validator('items')
    def validate_items(cls, v):
        if not v:
            raise ValueError('At least one item is required')
        return v

class PembelianUpdate(BaseModel):
    no_pembelian: Optional[str] = None
    warehouse_id: Optional[int] = None
    customer_id: Optional[str] = None
    top_id: Optional[int] = None
    sales_date: Optional[datetime] = None
    sales_due_date: Optional[datetime] = None
    discount: Optional[Decimal] = None
    tax : Optional[int] = None
    additional_discount: Optional[Decimal] = None
    expense: Optional[Decimal] = None
    items: Optional[List[PembelianItemUpdate]] = None

    @validator('no_pembelian')
    def validate_no_pembelian(cls, v):
        if v is not None and (not v or v.strip() == ""):
            raise ValueError('No pembelian cannot be empty')
        return v.strip() if v else v

    @validator('discount', 'additional_discount', 'expense')
    def validate_amounts(cls, v):
        if v is not None and v < 0:
            raise ValueError('Amount cannot be negative')
        return v

class PembelianResponse(BaseModel):
    id: int
    no_pembelian: str
    status_pembayaran: StatusPembayaranEnum
    status_pembelian: StatusPembelianEnum

    sales_date: Optional[datetime] = None
    sales_due_date: Optional[datetime] = None

    # Financial fields
    discount: Decimal
    additional_discount: Decimal
    expense: Decimal
    total_qty: int
    total_price: Decimal

    # Draft mode fields
    warehouse_id: Optional[int] = None
    customer_id: Optional[str] = None
    top_id: Optional[int] = None

    # Finalized mode fields
    warehouse_name: Optional[str] = None
    customer_name: Optional[str] = None
    top_name: Optional[str] = None
    currency_name: Optional[str] = None


    # Related data
    items: List[PembelianItemResponse] = Field(default_factory=list, alias="pembelian_items")
    attachments: List[AttachmentResponse] = Field(default_factory=list)

    class Config:
        from_attributes = True

class PembelianStatusUpdate(BaseModel):
    status_pembelian: Optional[StatusPembelianEnum] = None
    status_pembayaran: Optional[StatusPembayaranEnum] = None

class PembelianListResponse(BaseModel):
    id: int
    no_pembelian: str
    status_pembayaran: StatusPembayaranEnum
    status_pembelian: StatusPembelianEnum
    sales_date: Optional[datetime] = None
    total_qty: int
    total_price: Decimal
    total_paid: Decimal

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

# Error response
class ErrorResponse(BaseModel):
    detail: str
    error_code: Optional[str] = None

# Success response
class SuccessResponse(BaseModel):
    message: str
    data: Optional[dict] = None

# Totals calculation response
class TotalsResponse(BaseModel):
    subtotal: Decimal  # Sum of all item totals
    discount: Decimal
    additional_discount: Decimal
    expense: Decimal
    total_qty: int
    final_total: Decimal  # subtotal - discount - additional_discount + expense

    class Config:
        from_attributes = True