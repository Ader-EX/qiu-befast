from datetime import timedelta, datetime
from decimal import Decimal
from typing import List, Optional

from fastapi import FastAPI,  APIRouter

from fastapi.params import Depends, Query
from sqlalchemy import extract, func
from sqlalchemy.orm import Session
from starlette import status

from starlette.exceptions import HTTPException

from models.Customer import Customer
from models.Item import Item
from models.Pembelian import Pembelian, StatusPembelianEnum
from models.Penjualan import Penjualan, PenjualanItem
from schemas.PaginatedResponseSchemas import PaginatedResponse
from schemas.UserSchemas import UserCreate, TokenSchema, RequestDetails, UserOut, UserUpdate, UserType
from database import  get_db
from schemas.UtilsSchemas import DashboardStatistics, LabaRugiResponse, SalesReportRow, SalesReportResponse
from utils import get_hashed_password, verify_password, create_access_token, create_refresh_token
from models.User import User

router =APIRouter()


def get_status(this_month: float, last_month: float) -> str:
    if this_month > last_month:
        return "up"
    elif this_month < last_month:
        return "down"
    else:
        return "neutral"

@router.get("/statistics", status_code=status.HTTP_200_OK, response_model=DashboardStatistics)
async def get_dashboard_statistics(db: Session = Depends(get_db)):
    now = datetime.now()
    this_month = now.month
    this_year = now.year
    last_month = (now.replace(day=1) - timedelta(days=1)).month
    last_month_year = (now.replace(day=1) - timedelta(days=1)).year

    # Products
    total_products = db.query(Item).count()
    this_month_products = db.query(Item).filter(
        extract('month', Item.created_at) == this_month,
        extract('year', Item.created_at) == this_year
    ).count()
    last_month_products = db.query(Item).filter(
        extract('month', Item.created_at) == last_month,
        extract('year', Item.created_at) == last_month_year
    ).count()
    percentage_month_products = ((this_month_products - last_month_products) / last_month_products * 100) if last_month_products > 0 else 100.0 if this_month_products > 0 else 0.0
    status_month_products = get_status(this_month_products, last_month_products)

    # Customers
    total_customer = db.query(Customer).count()
    this_month_customer = db.query(Customer).filter(
        extract('month', Customer.created_at) == this_month,
        extract('year', Customer.created_at) == this_year
    ).count()
    last_month_customer = db.query(Customer).filter(
        extract('month', Customer.created_at) == last_month,
        extract('year', Customer.created_at) == last_month_year
    ).count()
    percentage_month_customer = ((this_month_customer - last_month_customer) / last_month_customer * 100) if last_month_customer > 0 else 100.0 if this_month_customer > 0 else 0.0
    status_month_customer = get_status(this_month_customer, last_month_customer)

    # Pembelian
    total_pembelian = db.query(func.coalesce(func.sum(Pembelian.total_price), 0)).scalar()
    this_month_pembelian = db.query(func.coalesce(func.sum(Pembelian.total_price), 0)).filter(
        extract('month', Pembelian.created_at) == this_month,
        extract('year', Pembelian.created_at) == this_year
    ).scalar() or 0
    last_month_pembelian = db.query(func.coalesce(func.sum(Pembelian.total_price), 0)).filter(
        extract('month', Pembelian.created_at) == last_month,
        extract('year', Pembelian.created_at) == last_month_year
    ).scalar() or 0
    percentage_month_pembelian = ((this_month_pembelian - last_month_pembelian) / last_month_pembelian * 100) if last_month_pembelian > 0 else 100.0 if this_month_pembelian > 0 else 0.0
    status_month_pembelian = get_status(this_month_pembelian, last_month_pembelian)

    # Penjualan
    total_penjualan = db.query(func.coalesce(func.sum(Penjualan.total_price), 0)).scalar()
    this_month_penjualan = db.query(func.coalesce(func.sum(Penjualan.total_price), 0)).filter(
        extract('month', Penjualan.created_at) == this_month,
        extract('year', Penjualan.created_at) == this_year
    ).scalar() or 0
    last_month_penjualan = db.query(func.coalesce(func.sum(Penjualan.total_price), 0)).filter(
        extract('month', Penjualan.created_at) == last_month,
        extract('year', Penjualan.created_at) == last_month_year
    ).scalar() or 0
    percentage_month_penjualan = ((this_month_penjualan - last_month_penjualan) / last_month_penjualan * 100) if last_month_penjualan > 0 else 100.0 if this_month_penjualan > 0 else 0.0
    status_month_penjualan = get_status(this_month_penjualan, last_month_penjualan)

    return DashboardStatistics(
        total_products=total_products,
        percentage_month_products=percentage_month_products,
        status_month_products=status_month_products,

        total_customer=total_customer,
        percentage_month_customer=percentage_month_customer,
        status_month_customer=status_month_customer,

        total_pembelian=total_pembelian,
        percentage_month_pembelian=percentage_month_pembelian,
        status_month_pembelian=status_month_pembelian,

        total_penjualan=total_penjualan,
        percentage_month_penjualan=percentage_month_penjualan,
        status_month_penjualan=status_month_penjualan
    )

@router.get("/laba-rugi", status_code=status.HTTP_200_OK, response_model=LabaRugiResponse)
async def get_laba_rugi(
        from_date: datetime = Query(..., description="Start datetime (ISO-8601)"),
        to_date: Optional[datetime] = Query(None, description="End datetime (ISO-8601)"),
        db: Session = Depends(get_db),
):

    if to_date is None:
        to_date = datetime.now()

    total_pembelian = (
        db.query(func.coalesce(func.sum(Pembelian.total_price), 0))
        .filter(
            Pembelian.is_deleted.is_(False),
            Pembelian.status_pembelian != StatusPembelianEnum.DRAFT,
            Pembelian.created_at >= from_date,
            Pembelian.created_at <= to_date,
            )
        .scalar()
    )

    total_penjualan = (
        db.query(func.coalesce(func.sum(Penjualan.total_price), 0))
        .filter(
            Penjualan.is_deleted.is_(False),
            Penjualan.status_penjualan != StatusPembelianEnum.DRAFT,
            Penjualan.created_at >= from_date,
            Penjualan.created_at <= to_date,
            )
        .scalar()
    )

    profit_or_loss = total_penjualan - total_pembelian

    return LabaRugiResponse(
        total_pembelian=total_pembelian,
        total_penjualan=total_penjualan,
        profit_or_loss=profit_or_loss
    )



@router.get(
    "/penjualan",
    status_code=status.HTTP_200_OK,
    response_model=SalesReportResponse,
    summary="Laporan Penjualan (detail per item)",
)
async def get_penjualan_laporan(
        from_date: datetime = Query(..., description="Start datetime (inclusive)"),
        to_date: Optional[datetime] = Query(None, description="End datetime (inclusive)"),
        db: Session = Depends(get_db),
):
    """
    Requirements implemented:
    - Title: 'Laporan Penjualan [Date From - Date To]'
    - penjualan.status != 'DRAFT' AND is_deleted = false
    - Filter by Penjualan.sales_date BETWEEN from_date AND to_date
    - Join detail items to produce table columns
    """

    if to_date is None:
        to_date = datetime.now()

    # Pull all required columns in one go
    rows = (
        db.query(
            Penjualan.sales_date.label("date"),
            # Prefer stored name; fall back to related object name
            Penjualan.customer_name.label("customer_name_stored"),
            Customer.name.label("customer_name_rel"),
            # if your schema doesn't have this, keep it here and add the column; otherwise it will be None below
            getattr(Penjualan, "kode_lambung", None).label("kode_lambung")  # type: ignore
            if hasattr(Penjualan, "kode_lambung") else Penjualan.no_penjualan.label("kode_lambung_placeholder"),
            Penjualan.no_penjualan,
            Penjualan.status_pembayaran,   # display as "Paid/Unpaid"
            PenjualanItem.item_sku,
            PenjualanItem.item_name,
            PenjualanItem.qty,
            PenjualanItem.unit_price,
            PenjualanItem.discount,
            PenjualanItem.tax_percentage,
        )
        .join(Customer, Customer.id == Penjualan.customer_id, isouter=True)
        .join(PenjualanItem, PenjualanItem.penjualan_id == Penjualan.id)
        .filter(
            Penjualan.is_deleted.is_(False),
            Penjualan.status_penjualan != StatusPembelianEnum.DRAFT,
            Penjualan.sales_date >= from_date,
            Penjualan.sales_date <= to_date,
            )
        .order_by(Penjualan.sales_date.asc(), Penjualan.no_penjualan.asc(), PenjualanItem.id.asc())
        .all()
    )

    def _dec(x) -> Decimal:
        return Decimal(str(x or 0))

    report_rows: List[SalesReportRow] = []
    for r in rows:
        qty = int(r.qty or 0)
        price = _dec(r.unit_price)
        sub_total = price * qty
        discount = _dec(r.discount)
        total = sub_total - discount
        if total < 0:
            total = Decimal("0")
        tax_pct = Decimal(str(r.tax_percentage or 0))
        tax = (total * tax_pct / Decimal(100))
        grand_total = total + tax

        report_rows.append(
            SalesReportRow(
                date=r.date,
                customer=r.customer_name_stored or r.customer_name_rel or "—",
                kode_lambung=getattr(r, "kode_lambung", None) if hasattr(r, "kode_lambung") else None,
                no_penjualan=r.no_penjualan,
                status=(r.status_pembayaran.name.capitalize() if hasattr(r.status_pembayaran, "name")
                        else str(r.status_pembayaran)),
                item_code=r.item_sku,
                item_name=r.item_name,
                qty=qty,
                price=price,
                sub_total=sub_total,
                total=total,
                tax=tax,
                grand_total=grand_total,
            )
        )

    title = f"Laporan Penjualan {from_date:%d/%m/%Y} - {to_date:%d/%m/%Y}"
    return SalesReportResponse(
        title=title,
        date_from=from_date,
        date_to=to_date,
        rows=report_rows,
    )