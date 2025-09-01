from pydantic import BaseModel, field_validator, Field, model_validator
from typing import Optional, List
from datetime import datetime
from decimal import Decimal
from enum import Enum

from pydantic_core.core_schema import ValidationInfo

from models.Pembelian import StatusPembayaranEnum, StatusPembelianEnum
import enum

from schemas.PembelianSchema import PembelianResponse
from schemas.PenjualanSchema import AttachmentResponse, PenjualanResponse


# Enums
class PembayaranPengembalianType(str, Enum):
    PEMBELIAN = "PEMBELIAN"
    PENJUALAN = "PENJUALAN"



# Payment Detail schemas
class PembayaranDetailBase(BaseModel):
    pembelian_id: Optional[int] = None
    penjualan_id: Optional[int] = None
    total_paid: Decimal = Field(default=Decimal('0.00'), ge=0)

class PembayaranDetailCreate(PembayaranDetailBase):
    @model_validator(mode='after')
    def validate_reference_ids(self):
        # Exactly one of pembelian_id or penjualan_id must be provided
        if not self.pembelian_id and not self.penjualan_id:
            raise ValueError('Either pembelian_id or penjualan_id must be provided')

        if self.pembelian_id and self.penjualan_id:
            raise ValueError('Only one of pembelian_id or penjualan_id can be provided')

        return self





class PembayaranDetailResponse(PembayaranDetailBase):
    id: int
    pembayaran_id: int

    # Related objects
    pembelian_rel: Optional['PembelianResponse'] = None
    penjualan_rel: Optional['PenjualanResponse'] = None

    class Config:
        from_attributes = True

# Base schemas
class PembayaranBase(BaseModel):
    payment_date: datetime
    reference_type: PembayaranPengembalianType
    currency_id: int
    warehouse_id: int


class PembayaranCreate(PembayaranBase):
    customer_id: Optional[str] = None
    vendor_id: Optional[str] = None
    pembayaran_details: List[PembayaranDetailCreate] = Field(..., min_length=1)

    @model_validator(mode='after')
    def validate_details_consistency(self):
        reference_type = self.reference_type

        for detail in self.pembayaran_details:
            if reference_type == PembayaranPengembalianType.PEMBELIAN:
                if not detail.pembelian_id:
                    raise ValueError('All payment details must have pembelian_id when reference_type is PEMBELIAN')
                if detail.penjualan_id:
                    raise ValueError('Payment details cannot have penjualan_id when reference_type is PEMBELIAN')
            elif reference_type == PembayaranPengembalianType.PENJUALAN:
                if not detail.penjualan_id:
                    raise ValueError('All payment details must have penjualan_id when reference_type is PENJUALAN')
                if detail.pembelian_id:
                    raise ValueError('Payment details cannot have pembelian_id when reference_type is PENJUALAN')

        return self

class PembayaranUpdate(BaseModel):
    reference_type : Optional[PembayaranPengembalianType] = None
    payment_date: Optional[datetime] = None
    currency_id: Optional[int] = None
    warehouse_id: Optional[int] = None

    pembayaran_details: Optional[List[PembayaranDetailCreate]] = None

# Response schemas with related data
class CustomerResponse(BaseModel):
    id: int
    code: str
    name: str
    address: Optional[str] = None

    class Config:
        from_attributes = True

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


class PembayaranResponse(BaseModel):
    id: int
    no_pembayaran: str
    status: StatusPembelianEnum
    created_at: datetime
    payment_date: datetime

    reference_type: PembayaranPengembalianType
    customer_id: Optional[int] = None
    vendor_id: Optional[str] = None
    currency_id: int
    warehouse_id: int
    attachments: List[AttachmentResponse] = Field(default_factory=list)


    customer_rel: Optional[CustomerResponse] = None
    warehouse_rel: Optional[WarehouseResponse] = None
    curr_rel: Optional[CurrencyResponse] = None
    pembayaran_details: List[PembayaranDetailResponse] = []

    # Computed fields
    reference_numbers: List[str] = Field(default_factory=list)
    reference_partners: List[str] = Field(default_factory=list)

    class Config:
        from_attributes = True

    @field_validator('reference_numbers', mode='before')
    @classmethod
    def set_reference_numbers(cls, v, info: ValidationInfo):
        if info.data and 'pembayaran_details' in info.data:
            details = info.data['pembayaran_details']
            numbers = []

            for detail in details:
                if hasattr(detail, 'pembelian_rel') and detail.pembelian_rel:
                    numbers.append(detail.pembelian_rel.no_pembelian)
                elif hasattr(detail, 'penjualan_rel') and detail.penjualan_rel:
                    numbers.append(detail.penjualan_rel.no_penjualan)

            return numbers
        return v or []

    @field_validator('reference_partners', mode='before')
    @classmethod
    def set_reference_partners(cls, v, info: ValidationInfo):
        if info.data and 'pembayaran_details' in info.data:
            details = info.data['pembayaran_details']
            partners = []

            for detail in details:
                if hasattr(detail, 'pembelian_rel') and detail.pembelian_rel:
                    partners.append(detail.pembelian_rel.vendor_display or '—')
                elif hasattr(detail, 'penjualan_rel') and detail.penjualan_rel:
                    partners.append(detail.penjualan_rel.customer_display or '—')

            return partners
        return v or []

class PembayaranListResponse(BaseModel):
    data: List[PembayaranResponse]
    total: int
    skip: int
    limit: int

# Filter schema for queries
class PembayaranFilter(BaseModel):
    reference_type: Optional[PembayaranPengembalianType] = None
    customer_id: Optional[str] = None
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


PembayaranDetailResponse.model_rebuild()
PembayaranResponse.model_rebuild()