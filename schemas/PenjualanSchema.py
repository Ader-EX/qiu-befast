# schemas/penjualan.py
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator, model_validator, AliasChoices, ConfigDict

from models.Pembelian import StatusPembayaranEnum, StatusPembelianEnum
from schemas.ItemSchema import ItemResponse
from schemas.KodeLambungSchema import KodeLambungResponse
# ---------------------------------
# Helpers / common aliases & types
# ---------------------------------
NonNegDec = Decimal


class PenjualanItemBase(BaseModel):
    item_id: Optional[int] = None
    discount: NonNegDec = Field(default=Decimal("0.00"), ge=0)
    qty: int = Field(gt=0)                                   # must be > 0
    unit_price: NonNegDec = Field(ge=0)                      # cannot be negative
    unit_price_rmb: NonNegDec = Field(ge=0)            # cannot be negative
    tax_percentage: int = Field(default=0, ge=0, le=100)     # 0..100

class PenjualanItemCreate(PenjualanItemBase):
    item_id: int

class PenjualanItemUpdate(PenjualanItemBase):
    item_id: int


class PenjualanItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: int
    penjualan_id: int

    # FK ref (present while DRAFT)
    item_id: Optional[int] = None

    # Quantities & pricing inputs
    qty: int
    unit_price: NonNegDec
    unit_price_rmb: NonNegDec
    tax_percentage: int = 0
    discount: NonNegDec = Decimal("0.00")

    # Calculated fields (match model fields you added)
    price_after_tax: NonNegDec = Decimal("0.00")
    sub_total: NonNegDec = Decimal("0.00")
    total_price: NonNegDec = Decimal("0.00")

    # Optional related item (handy in draft)
    item: Optional[ItemResponse] = Field(
        default=None,
        validation_alias=AliasChoices("item_rel", "item"),
    )


# ================================
# Attachment (shared)
# ================================

class AttachmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    filename: str
    file_size: Optional[int] = None
    mime_type: Optional[str] = None
    file_path: Optional[str] = None
    created_at: datetime


# ================================
# Penjualan Schemas (header mirrors Pembelian)
# ================================

class PenjualanBase(BaseModel):
    no_penjualan: Optional[str] = None
    warehouse_id: Optional[int] = None
    customer_id: Optional[int] = None
    top_id: Optional[int] = None
    sales_date: Optional[datetime] = None
    kode_lambung_id: Optional[int] = None
    sales_due_date: Optional[datetime] = None
    additional_discount: Optional[NonNegDec] = Decimal("0.00")
    expense: Optional[NonNegDec] = Decimal("0.00")


class PenjualanCreate(BaseModel):
    warehouse_id: Optional[int] = None
    customer_id: Optional[int] = None
    top_id: Optional[int] = None
    sales_date: Optional[datetime] = None
    sales_due_date: Optional[datetime] = None
    additional_discount: Optional[NonNegDec] = Decimal("0.00")
    expense: Optional[NonNegDec] = Decimal("0.00")
    items: List[PenjualanItemCreate] = Field(default_factory=list)
    currency_amount : float = Decimal("0.00")
    kode_lambung_id: int

    @model_validator(mode="after")
    def _require_items(self):
        if not self.items:
            raise ValueError("At least one item is required")
        return self


class PenjualanUpdate(BaseModel):
    no_penjualan: Optional[str] = None
    warehouse_id: Optional[int] = None
    customer_id: Optional[int] = None
    top_id: Optional[int] = None
    sales_date: Optional[datetime] = None
    kode_lambung: Optional[str] = None
    kode_lambung_id: Optional[int] = None
    sales_due_date: Optional[datetime] = None
    additional_discount: Optional[NonNegDec] = None
    expense: Optional[NonNegDec] = None
    items: Optional[List[PenjualanItemUpdate]] = None

    @field_validator("no_penjualan")
    @classmethod
    def _validate_no_penjualan(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        s = v.strip()
        if not s:
            raise ValueError("No penjualan cannot be empty")
        return s


class PenjualanResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: int
    no_penjualan: str
    status_pembayaran: StatusPembayaranEnum
    status_penjualan: StatusPembelianEnum

    sales_date: Optional[datetime] = None
    sales_due_date: Optional[datetime] = None
    created_at: datetime
    currency_amount : Optional[NonNegDec] = None

    # Financial fields (mirror Pembelian header; match Penjualan model)
    total_subtotal: NonNegDec = Decimal("0.00")
    total_discount: NonNegDec = Decimal("0.00")
    additional_discount: NonNegDec = Decimal("0.00")
    total_before_discount: NonNegDec = Decimal("0.00")
    total_tax: NonNegDec = Decimal("0.00")
    expense: NonNegDec = Decimal("0.00")
    total_price: NonNegDec = Decimal("0.00")
    total_paid: NonNegDec = Decimal("0.00")
    total_return: NonNegDec = Decimal("0.00")

    # Legacy/supporting field still present on model
    total_qty: int = 0

    # Draft-mode FKs
    warehouse_id: Optional[int] = None
    customer_id: Optional[int] = None
    top_id: Optional[int] = None
    kode_lambung_id: Optional[int] = None

    # Finalized snapshot names
    warehouse_name: Optional[str] = None
    customer_name: Optional[str] = None
    top_name: Optional[str] = None
    currency_name: Optional[str] = None
    kode_lambung_name: Optional[str] = None

    # Computed helpers from model
    remaining: Optional[NonNegDec] = None
    customer_display: Optional[str] = None
    customer_address_display: Optional[str] = None
    kode_lambung_display: Optional[str] = None

    # Relations
    items: List[PenjualanItemResponse] = Field(
        default_factory=list,
        validation_alias=AliasChoices("penjualan_items", "items"),
    )
    attachments: List[AttachmentResponse] = Field(default_factory=list)
    kode_lambung: Optional[KodeLambungResponse] = Field(
        default=None,
        validation_alias=AliasChoices("kode_lambung_rel", "kode_lambung"),
    )


class PenjualanStatusUpdate(BaseModel):
    status_penjualan: Optional[StatusPembelianEnum] = None  # fixed name
    status_pembayaran: Optional[StatusPembayaranEnum] = None


class PenjualanListResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    no_penjualan: str
    status_pembayaran: StatusPembayaranEnum
    status_penjualan: StatusPembelianEnum
    sales_date: Optional[datetime] = None

    # Totals (aligned to list response you use in routes)
    total_price: NonNegDec
    total_paid: NonNegDec
    total_return: NonNegDec
    remaining: NonNegDec
    customer_name : str
    kode_lambung_name: Optional[str] = None

    # Optional counts & names
    items_count: int = 0
    attachments_count: int = 0
    customer_name: Optional[str] = None
    warehouse_name: Optional[str] = None


# ================================
# Upload / Error / Success (shared)
# ================================

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


# ================================
# Totals Response (mirror Pembelian)
# ================================

class TotalsResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    total_subtotal: NonNegDec
    total_discount: NonNegDec
    additional_discount: NonNegDec
    total_before_discount: NonNegDec
    total_tax: NonNegDec
    expense: NonNegDec
    total_price: NonNegDec
