from pydantic import BaseModel, validator, Field
from typing import Optional, List
from datetime import datetime
from decimal import Decimal
from enum import Enum

from models.Pembelian import StatusPembayaranEnum, StatusPembelianEnum

# Enums
class PembayaranPengembalianType(str, Enum):
    PEMBELIAN = "PEMBELIAN"
    PENJUALAN = "PENJUALAN"

# Base schemas
class PembayaranBase(BaseModel):
    payment_date: datetime
    total_paid: Decimal = Field(default=Decimal('0.00'), ge=0)
    reference_type: PembayaranPengembalianType
    currency_id: int
    warehouse_id: int
    warehouse_name: Optional[str] = None
    customer_name: Optional[str] = None
    currency_name: Optional[str] = None

class PembayaranCreate(PembayaranBase):
    pembelian_id: Optional[int] = None
    penjualan_id: Optional[int] = None
    customer_id: Optional[str] = None
    vendor_id: Optional[str] = None

    @validator('pembelian_id', 'penjualan_id')
    def validate_reference_ids(cls, v, values):
        reference_type = values.get('reference_type')
        if reference_type == PembayaranPengembalianType.PEMBELIAN:
            if 'pembelian_id' in values and not values['pembelian_id']:
                raise ValueError('pembelian_id is required when reference_type is PEMBELIAN')
            if 'penjualan_id' in values and values['penjualan_id']:
                raise ValueError('penjualan_id must be None when reference_type is PEMBELIAN')
        elif reference_type == PembayaranPengembalianType.PENJUALAN:
            if 'penjualan_id' in values and not values['penjualan_id']:
                raise ValueError('penjualan_id is required when reference_type is PENJUALAN')
            if 'pembelian_id' in values and values['pembelian_id']:
                raise ValueError('pembelian_id must be None when reference_type is PENJUALAN')
        return v

    @validator('customer_id', 'vendor_id')
    def validate_customer_vendor_ids(cls, v, values):
        reference_type = values.get('reference_type')
        if reference_type == PembayaranPengembalianType.PEMBELIAN and 'vendor_id' in values:
            if not v:
                raise ValueError('vendor_id is required when reference_type is PEMBELIAN')
        elif reference_type == PembayaranPengembalianType.PENJUALAN and 'customer_id' in values:
            if not v:
                raise ValueError('customer_id is required when reference_type is PENJUALAN')
        return v

class PembayaranUpdate(BaseModel):
    payment_date: Optional[datetime] = None
    total_paid: Optional[Decimal] = Field(None, ge=0)
    currency_id: Optional[int] = None
    warehouse_id: Optional[int] = None
    warehouse_name: Optional[str] = None
    customer_name: Optional[str] = None
    currency_name: Optional[str] = None

# Response schemas with related data
class CustomerResponse(BaseModel):
    id: str
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

class PembelianResponse(BaseModel):
    id: int
    no_pembelian: str
    status_pembayaran: StatusPembayaranEnum
    status_pembelian: StatusPembelianEnum
    total_price: Decimal
    total_paid: Decimal
    total_return: Decimal
    remaining: Decimal
    vendor_display: str
    sales_date: Optional[datetime] = None
    sales_due_date: Optional[datetime] = None

    class Config:
        from_attributes = True

class PenjualanResponse(BaseModel):
    id: int
    no_penjualan: str
    status_pembayaran: StatusPembayaranEnum
    status_penjualan: StatusPembelianEnum
    total_price: Decimal
    total_paid: Decimal
    total_return: Decimal
    remaining: Decimal
    customer_display: str
    sales_date: Optional[datetime] = None
    sales_due_date: Optional[datetime] = None

    class Config:
        from_attributes = True

class PembayaranResponse(BaseModel):
    id: int
    created_at: datetime
    payment_date: datetime
    total_paid: Decimal
    pembelian_id: Optional[int] = None
    penjualan_id: Optional[int] = None
    reference_type: PembayaranPengembalianType
    customer_id: Optional[str] = None
    vendor_id: Optional[str] = None
    currency_id: int
    warehouse_id: int
    warehouse_name: Optional[str] = None
    customer_name: Optional[str] = None
    currency_name: Optional[str] = None
    
    # Related objects
    customer_rel: Optional[CustomerResponse] = None
    warehouse_rel: Optional[WarehouseResponse] = None
    curr_rel: Optional[CurrencyResponse] = None
    pembelian_rel: Optional[PembelianResponse] = None
    penjualan_rel: Optional[PenjualanResponse] = None

    # Computed fields
    reference_no: Optional[str] = None
    reference_partner: Optional[str] = None
    reference_partner_address: Optional[str] = None

    class Config:
        from_attributes = True

    @validator('reference_no', pre=True, always=True)
    def set_reference_no(cls, v, values):
        if values.get('reference_type') == PembayaranPengembalianType.PEMBELIAN:
            pembelian = values.get('pembelian_rel')
            return pembelian.no_pembelian if pembelian else None
        elif values.get('reference_type') == PembayaranPengembalianType.PENJUALAN:
            penjualan = values.get('penjualan_rel')
            return penjualan.no_penjualan if penjualan else None
        return None

    @validator('reference_partner', pre=True, always=True)
    def set_reference_partner(cls, v, values):
        if values.get('reference_type') == PembayaranPengembalianType.PEMBELIAN:
            pembelian = values.get('pembelian_rel')
            return pembelian.vendor_display if pembelian else values.get('customer_name', '—')
        elif values.get('reference_type') == PembayaranPengembalianType.PENJUALAN:
            penjualan = values.get('penjualan_rel')
            return penjualan.customer_display if penjualan else values.get('customer_name', '—')
        return '—'

    @validator('reference_partner_address', pre=True, always=True)
    def set_reference_partner_address(cls, v, values):
        if values.get('reference_type') == PembayaranPengembalianType.PEMBELIAN:
            pembelian = values.get('pembelian_rel')
            return pembelian.vendor_address_display if pembelian else '—'
        elif values.get('reference_type') == PembayaranPengembalianType.PENJUALAN:
            penjualan = values.get('penjualan_rel')
            return penjualan.customer_address_display if penjualan else '—'
        return '—'

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
    date_from: Optional[datetime] = None
    date_to: Optional[datetime] = None
    min_amount: Optional[Decimal] = Field(None, ge=0)
    max_amount: Optional[Decimal] = Field(None, ge=0)

    @validator('max_amount')
    def validate_amount_range(cls, v, values):
        min_amount = values.get('min_amount')
        if min_amount is not None and v is not None and v < min_amount:
            raise ValueError('max_amount must be greater than or equal to min_amount')
        return v

# Summary schemas for reporting
class PembayaranSummary(BaseModel):
    total_payments: Decimal
    count: int
    reference_type: PembayaranPengembalianType

class PembayaranDailySummary(BaseModel):
    date: datetime
    total_pembelian: Decimal
    total_penjualan: Decimal
    count_pembelian: int
    count_penjualan: int