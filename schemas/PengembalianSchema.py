from pydantic import BaseModel, field_validator, Field, model_validator
from typing import Optional, List
from datetime import datetime
from decimal import Decimal
from enum import Enum

from pydantic_core.core_schema import ValidationInfo

from models.Pembelian import StatusPembayaranEnum, StatusPembelianEnum
import enum

from schemas.ItemSchema import AttachmentResponse
from schemas.PembelianSchema import PembelianResponse
from schemas.PenjualanSchema import PenjualanResponse
from schemas.PembayaranSchemas import CustomerResponse, PembayaranPengembalianType


# Return Detail schemas
class PengembalianDetailBase(BaseModel):
    pembelian_id: Optional[int] = None
    penjualan_id: Optional[int] = None
    total_return: Decimal = Field(default=Decimal('0.00'), ge=0)  # This represents the return amount

class PengembalianDetailCreate(PengembalianDetailBase):
    @model_validator(mode='after')
    def validate_reference_ids(self):
        # Exactly one of pembelian_id or penjualan_id must be provided
        if not self.pembelian_id and not self.penjualan_id:
            raise ValueError('Either pembelian_id or penjualan_id must be provided')

        if self.pembelian_id and self.penjualan_id:
            raise ValueError('Only one of pembelian_id or penjualan_id can be provided')

        return self


class PengembalianDetailResponse(PengembalianDetailBase):
    id: int
    pengembalian_id: int

    # Related objects
    pembelian_rel: Optional['PembelianResponse'] = None
    penjualan_rel: Optional['PenjualanResponse'] = None

    class Config:
        from_attributes = True

# Base schemas
class PengembalianBase(BaseModel):
    payment_date: datetime
    reference_type: PembayaranPengembalianType
    currency_id: int
    warehouse_id: int


class PengembalianCreate(PengembalianBase):
    customer_id: Optional[int] = None
    vendor_id: Optional[str] = None
    pengembalian_details: List[PengembalianDetailCreate] = Field(..., min_length=1)

    @model_validator(mode='after')
    def validate_details_consistency(self):
        reference_type = self.reference_type

        for detail in self.pengembalian_details:
            if reference_type == PembayaranPengembalianType.PEMBELIAN:
                if not detail.pembelian_id:
                    raise ValueError('All return details must have pembelian_id when reference_type is PEMBELIAN')
                if detail.penjualan_id:
                    raise ValueError('Return details cannot have penjualan_id when reference_type is PEMBELIAN')
            elif reference_type == PembayaranPengembalianType.PENJUALAN:
                if not detail.penjualan_id:
                    raise ValueError('All return details must have penjualan_id when reference_type is PENJUALAN')
                if detail.pembelian_id:
                    raise ValueError('Return details cannot have pembelian_id when reference_type is PENJUALAN')

        return self

class PengembalianUpdate(BaseModel):
    reference_type : Optional[PembayaranPengembalianType] = None
    payment_date: Optional[datetime] = None
    currency_id: Optional[int] = None
    warehouse_id: Optional[int] = None
    customer_id: Optional[int] = None
    vendor_id: Optional[str] = None

    pengembalian_details: Optional[List[PengembalianDetailCreate]] = None



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
    customer_id: Optional[int] = None
    vendor_id: Optional[str] = None
    currency_id: int
    warehouse_id: int

    customer_rel: Optional[CustomerResponse] = None
    warehouse_rel: Optional[WarehouseResponse] = None
    curr_rel: Optional[CurrencyResponse] = None
    pengembalian_details: List[PengembalianDetailResponse] = []
    attachments: List[AttachmentResponse] = []

    # Computed fields
    reference_numbers: List[str] = Field(default_factory=list)
    reference_partners: List[str] = Field(default_factory=list)

    class Config:
        from_attributes = True

    @field_validator('reference_numbers', mode='before')
    @classmethod
    def set_reference_numbers(cls, v, info: ValidationInfo):
        if info.data and 'pengembalian_details' in info.data:
            details = info.data['pengembalian_details']
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
        if info.data and 'pengembalian_details' in info.data:
            details = info.data['pengembalian_details']
            partners = []

            for detail in details:
                if hasattr(detail, 'pembelian_rel') and detail.pembelian_rel:
                    partners.append(detail.pembelian_rel.vendor_display or '—')
                elif hasattr(detail, 'penjualan_rel') and detail.penjualan_rel:
                    partners.append(detail.penjualan_rel.customer_display or '—')

            return partners
        return v or []

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


PengembalianDetailResponse.model_rebuild()
PengembalianResponse.model_rebuild()