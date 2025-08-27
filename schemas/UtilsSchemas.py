from decimal import Decimal

from pydantic import BaseModel


class DashboardStatistics(BaseModel):
    total_products: int
    percentage_month_products: float
    total_customer: int
    percentage_month_customer: float
    total_pembelian : Decimal
    percentage_month_pembelian : float
    total_penjualan : Decimal
    percentage_month_penjualan : float


