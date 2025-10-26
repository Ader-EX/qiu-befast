from datetime import datetime
from decimal import Decimal
from typing import Optional, List, Union

from pydantic import BaseModel, Field


class DashboardStatistics(BaseModel):
    total_products: int
    percentage_month_products: float
    status_month_products: str

    total_customer: int
    percentage_month_customer: float
    status_month_customer: str

    total_pembelian: Decimal
    percentage_month_pembelian: float
    status_month_pembelian: str

    total_penjualan: Decimal
    percentage_month_penjualan: float
    status_month_penjualan: str

class LabaRugiDetailRow(BaseModel):
    """
    Represents a detailed transaction row for the Profit and Loss calculation.
    All financial fields use Decimal for guaranteed precision.
    """
    # Key Identifiers and Date
    tanggal: datetime = Field(description="The date of the invoice (timestamp is typically ignored).")
    no_invoice: str = Field(description="The unique invoice identifier.")

    # Item Information
    item_code: str = Field(default="N/A", description="The code for the sold item.")
    item_name: str = Field(default="N/A", description="The name of the sold item.")

    # Quantity and Cost (HPP)
    qty_terjual: Decimal = Field(description="The quantity of the item sold. Uses Decimal for precision.")

    # HPP values (Cost of Goods Sold)
    hpp: Decimal = Field(default=Decimal("0"), description="The HPP (Cost of Goods Sold) per unit, derived from total_hpp / qty_terjual.")
    total_hpp: Decimal = Field(default=Decimal("0"), description="The total HPP for this line item.")

    # Sales/Revenue
    harga_jual: Decimal = Field(default=Decimal("0"), description="The unit selling price.")
    total_penjualan: Decimal = Field(default=Decimal("0"), description="The total revenue from this line item.")

    # Profit
    laba_kotor: Decimal = Field(default=Decimal("0"), description="The gross profit (total_penjualan - total_hpp).")
class LabaRugiResponse(BaseModel):
    """
    The final response model aggregating the Profit/Loss details and providing
    grand totals for a specified period.
    """
    title: str = Field(description="The title of the report.")
    date_from: datetime = Field(description="The starting date of the report period.")
    date_to: datetime = Field(description="The ending date of the report period.")
    total: int = Field(description="The total number of detail rows included in the report.")

    # Grand Totals (Financial fields use Decimal for precision)
    total_qty: Decimal = Field(default=Decimal("0"), description="The grand total quantity of items sold.")
    total_hpp: Decimal = Field(default=Decimal("0"), description="The grand total HPP (Cost of Goods Sold) for the period.")
    total_penjualan: Decimal = Field(default=Decimal("0"), description="The grand total revenue for the period.")
    total_laba_kotor: Decimal = Field(default=Decimal("0"), description="The grand total gross profit for the period.")

    # Details
    details: List[LabaRugiDetailRow] = Field(description="A list of all transaction detail rows.")


class SalesReportRow(BaseModel):
    date: datetime                         # Penjualan.sales_date
    sales_due_date: datetime    
    customer: str                          # Penjualan.customer_name or Customer.name
    kode_lambung_rel: Optional[str] = None     # Penjualan.kode_lambung  (if you have this column)
    kode_lambung_penjualan: Optional[str] = None
    no_penjualan: str                      # Penjualan.no_penjualan
    status: str                            # Payment status (e.g., "Paid")
    item_code: Optional[str] = None        # PenjualanItem.item_sku
    item_name: Optional[str] = None        # PenjualanItem.item_name
    qty: int                               # PenjualanItem.qty
    price: Decimal                         # PenjualanItem.unit_price
    sub_total: Decimal                     # qty * price
    total: Decimal                         # sub_total - discount
    tax: Decimal                           # total * (tax_percentage/100)
    grand_total: Decimal                   # total + tax

class CurrencyRelation(BaseModel):
    symbol: str

class SearchableSelectResponse(BaseModel):
    id: Union[str, int]
    name: str

class SearchableSelectResponseVendor(SearchableSelectResponse):
    curr_rel: CurrencyRelation


class SalesReportResponse(BaseModel):
    title: str
    date_from: datetime
    date_to: datetime
    data: List[SalesReportRow]
    total : int
    
    
    
class PurchaseReportRow(BaseModel):
    date: datetime
    sales_due_date: datetime
    vendor: str
    no_pembelian: str
    status: str  # "Paid/Unpaid/Half_paid" etc. (stringified enum)
    item_code: Optional[str] = None
    item_name: Optional[str] = None
    qty: int
    price: Decimal
    sub_total: Decimal
    total: Decimal
    tax: Decimal
    grand_total: Decimal

    class Config:
        # Ensure Decimals serialize cleanly to JSON
        json_encoders = {Decimal: lambda v: str(v)}


class PurchaseReportResponse(BaseModel):
    title: str
    date_from: datetime
    date_to: datetime
    data: List[PurchaseReportRow]
    total : int

    class Config:
        json_encoders = {Decimal: lambda v: str(v)}

class SalesTrendDataPoint(BaseModel):
    date: datetime
    order_count: int
    revenue: Decimal

    class Config:
        json_encoders = {
            Decimal: lambda v: float(v)
        }

class SalesTrendResponse(BaseModel):
    title: str
    period: str
    data: List[SalesTrendDataPoint]
    total_orders: int
    total_revenue: Decimal

    class Config:
        json_encoders = {
            Decimal: lambda v: float(v)
        }

class LowStockAlertResponse(BaseModel):
    sku : str
    item_name : str
    qty: int
    reorder_qty : int
    
    
    

class StockAdjustmentReportRow(BaseModel):
    """Single row in stock adjustment report"""
    date: datetime
    no_transaksi: str
    batch :str
    item_code: str
    item_name: str
    qty_masuk: int
    qty_keluar: int
    qty_balance: int
    harga_masuk: Decimal
    harga_keluar: Decimal
    hpp: Decimal

    class Config:
        from_attributes = True
        json_encoders = {
            Decimal: lambda v: float(v)
        }
        
class ItemStockAdjustmentReportRow(BaseModel):
    item_name : str
    data : List[StockAdjustmentReportRow]

class StockAdjustmentReportResponse(BaseModel):
    """Response for stock adjustment report"""
    title: str
    date_from: datetime
    date_to: datetime
    data: List[ItemStockAdjustmentReportRow]
    total: int

    class Config:
        from_attributes = True
        
    