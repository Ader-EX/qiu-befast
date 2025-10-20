from pydantic import BaseModel, field_validator, Field, model_validator
from typing import Optional, List
from datetime import datetime
from decimal import Decimal
from pydantic_core.core_schema import ValidationInfo

from models.Pembelian import StatusPembelianEnum
from schemas.ItemSchema import AttachmentResponse
from schemas.PembelianSchema import PembelianResponse
from schemas.PenjualanSchema import PenjualanResponse
from schemas.PembayaranSchemas import CustomerResponse, PembayaranPengembalianType


# Pengembalian Item schemas (NO discount, simpler than Pembelian)
class PengembalianItemBase(BaseModel):
    item_id: int
    qty_returned: int = Field(gt=0)
    unit_price: Decimal = Field(ge=0)
    tax_percentage: Optional[int] = Field(0, ge=0, le=100)


class PengembalianItemCreate(PengembalianItemBase):
    pass


class PengembalianItemUpdate(BaseModel):
    item_id: Optional[int] = None
    qty_returned: Optional[int] = Field(None, gt=0)
    unit_price: Optional[Decimal] = Field(None, ge=0)
    tax_percentage: Optional[int] = Field(None, ge=0, le=100)


class PengembalianItemResponse(BaseModel):
    id: int
    pengembalian_id: int
    item_id: Optional[int] = None
    item_code: Optional[str] = None
    item_name: Optional[str] = None
    
    qty_returned: int
    unit_price: Decimal
    tax_percentage: int
    
    # Computed totals
    sub_total: Decimal = Field(default=Decimal("0.00"))  # qty * unit_price
    total_return: Decimal = Field(default=Decimal("0.00"))  # sub_total + tax
    
    # Display properties
    item_display_code: str = Field(default="—")
    item_display_name: str = Field(default="—")
    primary_image_url: Optional[str] = None

    class Config:
        from_attributes = True


# Main Pengembalian schemas (NO additional_discount)
class PengembalianBase(BaseModel):
    payment_date: datetime
    reference_type: PembayaranPengembalianType
    currency_id: int
    warehouse_id: int
    notes: Optional[str] = None


class PengembalianCreate(PengembalianBase):
    # Single reference - exactly one must be provided based on reference_type
    pembelian_id: Optional[int] = None
    penjualan_id: Optional[int] = None
    
    customer_id: Optional[int] = None
    vendor_id: Optional[str] = None
    
    # Item list (required, at least 1 item)
    pengembalian_items: List[PengembalianItemCreate] = Field(..., min_length=1)

    @model_validator(mode='after')
    def validate_reference_and_partner(self):
        reference_type = self.reference_type

        # Validate reference ID based on type
        if reference_type == PembayaranPengembalianType.PEMBELIAN:
            if not self.pembelian_id:
                raise ValueError('pembelian_id is required when reference_type is PEMBELIAN')
            if self.penjualan_id:
                raise ValueError('penjualan_id should not be set when reference_type is PEMBELIAN')
            if not self.vendor_id:
                raise ValueError('vendor_id is required when reference_type is PEMBELIAN')
            if self.customer_id:
                raise ValueError('customer_id should not be set when reference_type is PEMBELIAN')
                
        elif reference_type == PembayaranPengembalianType.PENJUALAN:
            if not self.penjualan_id:
                raise ValueError('penjualan_id is required when reference_type is PENJUALAN')
            if self.pembelian_id:
                raise ValueError('pembelian_id should not be set when reference_type is PENJUALAN')
            if not self.customer_id:
                raise ValueError('customer_id is required when reference_type is PENJUALAN')
            if self.vendor_id:
                raise ValueError('vendor_id should not be set when reference_type is PENJUALAN')

        return self


class PengembalianUpdate(BaseModel):
    payment_date: Optional[datetime] = None
    currency_id: Optional[int] = None
    warehouse_id: Optional[int] = None
    notes: Optional[str] = None
    
    # Items can be updated (replace all items)
    pengembalian_items: Optional[List[PengembalianItemCreate]] = None


class VendorResponse(BaseModel):
    id: str
    name: str
    address: Optional[str] = None

    class Config:
        from_attributes = True


class WarehouseResponse(BaseModel):
    id: int
    name: str

    class Config:
        from_attributes = True


class CurrencyResponse(BaseModel):
    id: int
    name: str
    symbol: Optional[str] = None

    class Config:
        from_attributes = True


class PengembalianResponse(BaseModel):
    id: int
    no_pengembalian: str
    status: StatusPembelianEnum
    created_at: datetime
    payment_date: datetime

    reference_type: PembayaranPengembalianType
    pembelian_id: Optional[int] = None
    penjualan_id: Optional[int] = None
    
    customer_id: Optional[int] = None
    vendor_id: Optional[str] = None
    currency_id: int
    warehouse_id: int
    
    # Totals (simpler than Pembelian - no discounts)
    total_subtotal: Decimal = Field(default=Decimal("0.00"))
    total_tax: Decimal = Field(default=Decimal("0.00"))
    total_return: Decimal = Field(default=Decimal("0.00"))
    
    notes: Optional[str] = None

    # Relationships
    customer_rel: Optional[CustomerResponse] = None
    vend_rel: Optional[VendorResponse] = None
    warehouse_rel: Optional[WarehouseResponse] = None
    curr_rel: Optional[CurrencyResponse] = None
    pembelian_rel: Optional[PembelianResponse] = None
    penjualan_rel: Optional[PenjualanResponse] = None
    
    pengembalian_items: List[PengembalianItemResponse] = []
    attachments: List[AttachmentResponse] = []

    # Computed fields
    reference_number: str = Field(default="—")
    partner_display: str = Field(default="—")

    class Config:
        from_attributes = True


class PengembalianListResponse(BaseModel):
    data: List[PengembalianResponse]
    total: int
    skip: int
    limit: int


# Filter schema for queries
class PengembalianFilter(BaseModel):
    reference_type: Optional[PembayaranPengembalianType] = None
    customer_id: Optional[int] = None
    vendor_id: Optional[str] = None
    warehouse_id: Optional[int] = None
    currency_id: Optional[int] = None
    status: Optional[StatusPembelianEnum] = None
    date_from: Optional[datetime] = None
    date_to: Optional[datetime] = None
    min_amount: Optional[Decimal] = Field(None, ge=0)
    max_amount: Optional[Decimal] = Field(None, ge=0)

    @field_validator('max_amount')
    @classmethod
    def validate_amount_range(cls, v, info: ValidationInfo):
        if info.data and 'min_amount' in info.data:
            min_amount = info.data['min_amount']
            if min_amount is not None and v is not None and v < min_amount:
                raise ValueError('max_amount must be greater than or equal to min_amount')
        return v


PengembalianItemResponse.model_rebuild()
PengembalianResponse.model_rebuild()