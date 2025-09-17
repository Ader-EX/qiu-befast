from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator, model_validator, AliasChoices, ConfigDict

# If these are your own enums, import them from your models module:
from models.Pembelian import StatusPembayaranEnum, StatusPembelianEnum
from schemas.ItemSchema import ItemResponse


# -----------------------
# Helpers / Config
# -----------------------

NonNegDec = Decimal  


# -----------------------
# Item (PembelianItem) Schemas
# -----------------------

class PembelianItemBase(BaseModel):
    item_id: Optional[int] = None
    discount: Optional[NonNegDec] = Field(default=Decimal("0.00"), ge=0)
    qty: int = Field(gt=0)                         # must be > 0
    unit_price: NonNegDec = Field(ge=0)            # cannot be negative
    tax_percentage: int = Field(default=0, ge=0, le=100)   # 0-100%

class PembelianItemCreate(PembelianItemBase):
    item_id: int

class PembelianItemUpdate(PembelianItemBase):
    item_id: int


class PembelianItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: int
    pembelian_id: int

    # Item reference
    item_id: Optional[int] = None


    # Quantity and pricing
    qty: int
    unit_price: NonNegDec
    tax_percentage: int = 0
    discount: NonNegDec = Decimal("0.00")
    
    # Calculated fields (from your model)
    price_after_tax: NonNegDec = Decimal("0.00")
    sub_total: NonNegDec = Decimal("0.00")
    total_price: NonNegDec = Decimal("0.00")

    # Related item (only available in draft mode)
    item: Optional[ItemResponse] = Field(
        default=None,
        validation_alias=AliasChoices("item_rel", "item"),
    )


# -----------------------
# Attachment Schemas
# -----------------------

class AttachmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    filename: str
    file_size: Optional[int] = None
    mime_type: Optional[str] = None
    file_path: Optional[str] = None
    created_at: datetime


# -----------------------
# Pembelian (Purchase) Schemas
# -----------------------

class PembelianBase(BaseModel):
    no_pembelian: Optional[str] = None
    warehouse_id: Optional[int] = None
    sumberdana_id : Optional[int] = None
    vendor_id: Optional[str] = None  # String based on your model
    top_id: Optional[int] = None
    sales_date: Optional[datetime] = None
    sales_due_date: Optional[datetime] = None
    additional_discount: Optional[NonNegDec] = Decimal("0.00")
    expense: Optional[NonNegDec] = Decimal("0.00")


class PembelianCreate(BaseModel):
    warehouse_id: Optional[int] = None
    vendor_id: Optional[str] = None
    sumberdana_id : Optional[int] = None
    top_id: Optional[int] = None
    sales_date: Optional[datetime] = None
    sales_due_date: Optional[datetime] = None
    additional_discount: Optional[NonNegDec] = Decimal("0.00")
    expense: Optional[NonNegDec] = Decimal("0.00")
    items: List[PembelianItemCreate] = Field(default_factory=list)

    @model_validator(mode="after")
    def _require_items(self):
        if not self.items:
            raise ValueError("At least one item is required")
        return self


class PembelianUpdate(BaseModel):
    no_pembelian: Optional[str] = None
    warehouse_id: Optional[int] = None
    sumberdana_id : Optional[int] = None
    vendor_id: Optional[str] = None  # String based on your model
    top_id: Optional[int] = None
    sales_date: Optional[datetime] = None
    sales_due_date: Optional[datetime] = None
    additional_discount: Optional[NonNegDec] = None
    expense: Optional[NonNegDec] = None
    items: Optional[List[PembelianItemUpdate]] = None

    @field_validator("no_pembelian")
    @classmethod
    def _validate_no_pembelian(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        if not v.strip():
            raise ValueError("No pembelian cannot be empty")
        return v.strip()


class PembelianResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: int
    no_pembelian: str
    status_pembayaran: StatusPembayaranEnum
    status_pembelian: StatusPembelianEnum

    sales_date: Optional[datetime] = None
    sales_due_date: Optional[datetime] = None
    created_at: datetime

    # Financial fields - matching your model structure
    total_subtotal: NonNegDec = Decimal("0.00")
    total_discount: NonNegDec = Decimal("0.00")
    additional_discount: NonNegDec = Decimal("0.00")
    total_before_discount: NonNegDec = Decimal("0.00")
    total_tax: NonNegDec = Decimal("0.00")
    expense: NonNegDec = Decimal("0.00")
    total_price: NonNegDec = Decimal("0.00")
    total_paid: NonNegDec = Decimal("0.00")
    total_return: NonNegDec = Decimal("0.00")

    # Draft mode fields (ForeignKey references)
    warehouse_id: Optional[int] = None
    vendor_id: Optional[str] = None  # String in your model
    top_id: Optional[int] = None
    sumberdana_id : Optional[int] = None



    # Computed properties from hybrid_property
    remaining: Optional[NonNegDec] = None
    vendor_display: Optional[str] = None
    vendor_address_display: Optional[str] = None

    # Related data
    items: List[PembelianItemResponse] = Field(
        default_factory=list,
        validation_alias=AliasChoices("pembelian_items", "items"),
    )
    attachments: List[AttachmentResponse] = Field(default_factory=list)


class PembelianStatusUpdate(BaseModel):
    status_pembelian: Optional[StatusPembelianEnum] = None
    status_pembayaran: Optional[StatusPembayaranEnum] = None


class PembelianListResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    no_pembelian: str
    status_pembayaran: StatusPembayaranEnum
    status_pembelian: StatusPembelianEnum
    sales_date: Optional[datetime] = None
    
    # Financial totals
    total_price: NonNegDec
    total_paid: NonNegDec
    total_return: NonNegDec
    remaining: NonNegDec  # From hybrid property

    # Counts
    items_count: int = 0
    attachments_count: int = 0


# -----------------------
# Upload / Error / Success
# -----------------------

class FileUploadResponse(BaseModel):
    filename: str
    size: Optional[int] = None
    type: str

class UploadResponse(BaseModel):
    message: str
    files: List[FileUploadResponse] = Field(default_factory=list)

class ErrorResponse(BaseModel):
    detail: str
    error_code: Optional[str] = None

class SuccessResponse(BaseModel):
    message: str
    data: Optional[dict] = None


# -----------------------
# Totals (Updated to match your calculation logic)
# -----------------------

class TotalsResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    # Basic totals
    total_subtotal: NonNegDec
    total_discount: NonNegDec  # Item-level discounts
    additional_discount: NonNegDec  # Purchase-level discount
    total_before_discount: NonNegDec
    total_tax: NonNegDec
    expense: NonNegDec
    total_price: NonNegDec  # Grand total

