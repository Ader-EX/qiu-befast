import csv
from datetime import timedelta, datetime
from decimal import Decimal
import io
from typing import List, Optional

from fastapi import FastAPI,  APIRouter

from fastapi.params import Depends, Query
from fastapi.responses import StreamingResponse
from openpyxl import Workbook
from sqlalchemy import extract, func, literal, or_, union_all
from sqlalchemy.orm import Session, aliased
from starlette import status

from starlette.exceptions import HTTPException

from models.InventoryLedger import InventoryLedger
from models.KodeLambung import KodeLambung
from models.Customer import Customer
from models.Item import Item
from models.Pembelian import Pembelian, PembelianItem, StatusPembelianEnum
from models.Penjualan import Penjualan, PenjualanItem
from models.StockAdjustment import AdjustmentTypeEnum, StatusStockAdjustmentEnum, StockAdjustment, StockAdjustmentItem
from models.Vendor import Vendor
from schemas.PaginatedResponseSchemas import PaginatedResponse
from schemas.UserSchemas import UserCreate, TokenSchema, RequestDetails, UserOut, UserUpdate, UserType
from database import  get_db
from schemas.UtilsSchemas import DashboardStatistics, ItemStockAdjustmentReportRow, LabaRugiResponse, PurchaseReportResponse, PurchaseReportRow, \
    SalesReportRow, SalesReportResponse, SalesTrendResponse, SalesTrendDataPoint, StockAdjustmentReportResponse, StockAdjustmentReportRow
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
    
    # Better way to calculate last month
    first_day_this_month = now.replace(day=1)
    last_month_date = first_day_this_month - timedelta(days=1)
    last_month = last_month_date.month
    last_month_year = last_month_date.year

    # Helper function to safely calculate percentage
    def calculate_percentage(current, previous):
        if previous == 0:
            return 100.0 if current > 0 else 0.0
        return ((current - previous) / previous * 100)

    # Products
    total_products = db.query(Item).filter(Item.is_active == True).count()
    this_month_products = db.query(Item).filter(
        extract('month', Item.created_at) == this_month,
        extract('year', Item.created_at) == this_year
    ).count()
    last_month_products = db.query(Item).filter(
        extract('month', Item.created_at) == last_month,
        extract('year', Item.created_at) == last_month_year
    ).count()
    percentage_month_products = calculate_percentage(this_month_products, last_month_products)
    status_month_products = get_status(this_month_products, last_month_products)

    # Customers
    total_customer = db.query(Customer).filter(Customer.is_active == True).count()
    this_month_customer = db.query(Customer).filter(
        extract('month', Customer.created_at) == this_month,
        extract('year', Customer.created_at) == this_year
    ).count()
    last_month_customer = db.query(Customer).filter(
        extract('month', Customer.created_at) == last_month,
        extract('year', Customer.created_at) == last_month_year
    ).count()
    percentage_month_customer = calculate_percentage(this_month_customer, last_month_customer)
    status_month_customer = get_status(this_month_customer, last_month_customer)

    # Pembelian - More robust null handling
    total_pembelian = db.query(func.coalesce(func.sum(Pembelian.total_price), 0)).scalar() or 0
    this_month_pembelian = db.query(func.coalesce(func.sum(Pembelian.total_price), 0)).filter(
        extract('month', Pembelian.created_at) == this_month,
        extract('year', Pembelian.created_at) == this_year
    ).scalar() or 0
    last_month_pembelian = db.query(func.coalesce(func.sum(Pembelian.total_price), 0)).filter(
        extract('month', Pembelian.created_at) == last_month,
        extract('year', Pembelian.created_at) == last_month_year
    ).scalar() or 0
    percentage_month_pembelian = calculate_percentage(this_month_pembelian, last_month_pembelian)
    status_month_pembelian = get_status(this_month_pembelian, last_month_pembelian)

    # Penjualan - More robust null handling
    total_penjualan = db.query(func.coalesce(func.sum(Penjualan.total_price), 0)).scalar() or 0
    this_month_penjualan = db.query(func.coalesce(func.sum(Penjualan.total_price), 0)).filter(
        extract('month', Penjualan.created_at) == this_month,
        extract('year', Penjualan.created_at) == this_year
    ).scalar() or 0
    last_month_penjualan = db.query(func.coalesce(func.sum(Penjualan.total_price), 0)).filter(
        extract('month', Penjualan.created_at) == last_month,
        extract('year', Penjualan.created_at) == last_month_year
    ).scalar() or 0
    percentage_month_penjualan = calculate_percentage(this_month_penjualan, last_month_penjualan)
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
    "/laba-rugi/download",
    status_code=status.HTTP_200_OK,
    summary="Download Laporan Laba Rugi as XLSX",
)
async def download_laba_rugi(
    from_date: datetime = Query(..., description="Start datetime (ISO-8601)"),
    to_date: datetime | None = Query(None, description="End datetime (ISO-8601)"),
    db: Session = Depends(get_db),
):
    """
    Download profit and loss report (Laba Rugi) as XLSX file.
    Includes total pembelian, total penjualan, and calculated profit/loss.
    """

    if to_date is None:
        to_date = datetime.now()

    # Calculate totals
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

    # Calculate profit/loss
    profit_or_loss = Decimal(total_penjualan) - Decimal(total_pembelian)

    # Create workbook
    wb = Workbook()
    ws = wb.active
    ws.title = "Laba Rugi"

    # Write headers
    ws.append(["Laporan Laba Rugi"])
    ws.append([f"Periode: {from_date.strftime('%d/%m/%Y')} - {to_date.strftime('%d/%m/%Y')}"])
    ws.append([])  # empty line
    ws.append(["Deskripsi", "Total (Rp)"])

    # Write data rows
    ws.append(["Total Pembelian", float(total_pembelian)])
    ws.append(["Total Penjualan", float(total_penjualan)])
    ws.append(["Laba / Rugi", float(profit_or_loss)])

    # Optional: style headers (purely cosmetic)
    ws["A4"].font = ws["B4"].font.copy(bold=True)
    for col in ["A", "B"]:
        ws.column_dimensions[col].width = 25

    # Save to in-memory buffer
    output = io.BytesIO()
    wb.save(output)
    output.seek(0)

    filename = f"laba_rugi_{from_date:%Y%m%d}_{to_date:%Y%m%d}.xlsx"

    # Return as downloadable Excel file
    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"'
        },
    )

@router.get(
    "/penjualan",
    status_code=status.HTTP_200_OK,
    response_model=PaginatedResponse[SalesReportRow],
    summary="Laporan Penjualan (consolidated per sale)",
)

async def get_penjualan_laporan(
        from_date: datetime = Query(..., description="Start datetime (inclusive)"),
        to_date: Optional[datetime] = Query(None, description="End datetime (inclusive)"),
        customer_id: Optional[int] = Query(None, description="Customer ID"),
        kode_lambung_id: Optional[int] = Query(None, description="Kode Lambung ID"),
        skip: int = Query(0, ge=0, description="Number of records to skip"),
        limit: int = Query(100, ge=1, le=1000, description="Maximum number of records to return"),
        db: Session = Depends(get_db),
):
    """
    Returns one row per sale with concatenated item details and aggregated totals.
    Shows penjualan's kode_lambung only (Customer doesn't have a kode_lambung FK).
    """

    if to_date is None:
        to_date = datetime.now()

    sales_query = (
        db.query(
            Penjualan.id,
            Penjualan.sales_date.label("date"),
             Penjualan.sales_due_date,
            Penjualan.customer_name,
            Customer.name.label("customer_name_rel"),
            Penjualan.kode_lambung_id,
            KodeLambung.name.label("penjualan_kode_lambung"),
            Penjualan.no_penjualan,
            Penjualan.status_pembayaran,
        )
        .join(Customer, Customer.id == Penjualan.customer_id, isouter=True)
        .join(KodeLambung, KodeLambung.id == Penjualan.kode_lambung_id, isouter=True)
        .filter(
            Penjualan.is_deleted == False,
            Penjualan.status_penjualan != StatusPembelianEnum.DRAFT,
            Penjualan.sales_date >= from_date,
            Penjualan.sales_date <= to_date,
            )
    )

    if customer_id is not None:
        sales_query = sales_query.filter(Penjualan.customer_id == customer_id)

    if kode_lambung_id is not None:
        sales_query = sales_query.filter(Penjualan.kode_lambung_id == kode_lambung_id)

    sales_query = sales_query.order_by(Penjualan.sales_date.asc(), Penjualan.no_penjualan.asc())

    total_count = sales_query.count()
    sales = sales_query.offset(skip).limit(limit).all()

    def _dec(x) -> Decimal:
        return Decimal(str(x or 0))

    report_rows: List[SalesReportRow] = []

    for sale in sales:
        items = (
            db.query(
                PenjualanItem.qty,
                PenjualanItem.unit_price,
                PenjualanItem.discount,
                PenjualanItem.tax_percentage,
                Item.code.label("item_code"),
                Item.name.label("item_name"),
            )
            .join(Item, Item.id == PenjualanItem.item_id, isouter=True)
            .filter(PenjualanItem.penjualan_id == sale.id)
            .all()
        )

        item_codes, item_names = [], []
        total_subtotal = total_discount = total_tax = Decimal("0")
        total_qty = 0

        for it in items:
            qty = int(it.qty or 0)
            price = _dec(it.unit_price)
            discount = _dec(it.discount)
            tax_pct = Decimal(str(it.tax_percentage or 0))

            subtotal = price * qty
            total_after_discount = max(subtotal - discount, Decimal("0"))
            tax = total_after_discount * tax_pct / Decimal(100)

            item_codes.append(it.item_code or "N/A")
            item_names.append(it.item_name or "N/A")

            total_subtotal += subtotal
            total_discount += discount
            total_tax += tax
            total_qty += qty

        final_total = max(total_subtotal - total_discount, Decimal("0"))
        grand_total = final_total + total_tax

        report_rows.append(
            SalesReportRow(
                date=sale.date,
                sales_due_date=sale.sales_due_date,
                customer=sale.customer_name or sale.customer_name_rel or "—",
                kode_lambung_rel=sale.penjualan_kode_lambung,
                kode_lambung_penjualan=sale.penjualan_kode_lambung,
                no_penjualan=sale.no_penjualan,
                status=(sale.status_pembayaran.name.capitalize()
                        if hasattr(sale.status_pembayaran, "name")
                        else str(sale.status_pembayaran)),
                item_code=", ".join(item_codes) or "No items",
                item_name=", ".join(item_names) or "No items",
                qty=total_qty,
                price=(total_subtotal / total_qty) if total_qty > 0 else Decimal("0"),
                sub_total=total_subtotal,
                total=final_total,
                tax=total_tax,
                grand_total=grand_total,
            )
        )

    title = f"Laporan Penjualan {from_date:%d/%m/%Y} - {to_date:%d/%m/%Y}"
    return SalesReportResponse(
        title=title,
        date_from=from_date,
        date_to=to_date,
        data=report_rows,
        total=total_count,
    )
@router.get(
    "/penjualan/download",
    status_code=status.HTTP_200_OK,
    summary="Download Laporan Penjualan as CSV (all records)",
)


@router.get(
    "/penjualan/download",
    status_code=status.HTTP_200_OK,
    summary="Download Laporan Penjualan as XLSX (all records)",
)
async def download_penjualan_laporan(
    from_date: datetime = Query(..., description="Start datetime (inclusive)"),
    to_date: datetime | None = Query(None, description="End datetime (inclusive)"),
    customer_id: int | None = Query(None, description="Customer ID"),
    kode_lambung_id: int | None = Query(None, description="Kode Lambung ID"),
    db: Session = Depends(get_db),
):
    """
    Download complete sales report as XLSX without pagination.
    Returns all records matching the date filter — one row per sale with concatenated items.
    """

    if to_date is None:
        to_date = datetime.now()

    # Base query (same as before)
    sales_query = (
        db.query(
            Penjualan.id,
            Penjualan.sales_date.label("date"),
            Penjualan.sales_due_date,
            Penjualan.customer_name,
            Customer.name.label("customer_name_rel"),
            Penjualan.kode_lambung_id,
            KodeLambung.name.label("penjualan_kode_lambung"),
            Penjualan.no_penjualan,
            Penjualan.status_pembayaran,
        )
        .join(Customer, Customer.id == Penjualan.customer_id, isouter=True)
        .join(KodeLambung, KodeLambung.id == Penjualan.kode_lambung_id, isouter=True)
        .filter(
            Penjualan.is_deleted.is_(False),
            Penjualan.status_penjualan != StatusPembelianEnum.DRAFT,
            Penjualan.sales_date >= from_date,
            Penjualan.sales_date <= to_date,
        )
    )

    # Optional filters
    if customer_id is not None:
        sales_query = sales_query.filter(Penjualan.customer_id == customer_id)
    if kode_lambung_id is not None:
        sales_query = sales_query.filter(Penjualan.kode_lambung_id == kode_lambung_id)

    sales_query = sales_query.order_by(Penjualan.sales_date.asc(), Penjualan.no_penjualan.asc())
    sales = sales_query.all()

    def _dec(x) -> Decimal:
        return Decimal(str(x or 0))

    # Create Excel workbook
    wb = Workbook()
    ws = wb.active
    ws.title = "Laporan Penjualan"

    # Write header
    headers = [
        "Date",
        "Due Date",
        "Customer",
        "Kode Lambung",
        "No Penjualan",
        "Status",
        "Item Code",
        "Item Name",
        "Qty",
        "Price",
        "Sub Total",
        "Total",
        "Tax",
        "Grand Total",
    ]
    ws.append(headers)


    # Write rows
    for sale in sales:
        items_query = (
            db.query(
                PenjualanItem.qty,
                PenjualanItem.unit_price,
                PenjualanItem.discount,
                PenjualanItem.tax_percentage,
                Item.code.label("item_code"),
                Item.name.label("item_name"),
            )
            .join(Item, Item.id == PenjualanItem.item_id, isouter=True)
            .filter(PenjualanItem.penjualan_id == sale.id)
            .all()
        )

        item_codes, item_names = [], []
        total_subtotal, total_discount, total_tax = Decimal("0"), Decimal("0"), Decimal("0")
        total_qty = 0

        for item in items_query:
            item_code = item.item_code or "N/A"
            item_name = item.item_name or "N/A"
            qty = int(item.qty or 0)
            price = _dec(item.unit_price)
            item_subtotal = price * qty
            item_discount = _dec(item.discount)
            item_total = max(item_subtotal - item_discount, Decimal("0"))
            tax_pct = Decimal(str(item.tax_percentage or 0))
            item_tax = item_total * tax_pct / Decimal(100)

            item_codes.append(item_code)
            item_names.append(item_name)

            total_subtotal += item_subtotal
            total_discount += item_discount
            total_tax += item_tax
            total_qty += qty

        # Final totals
        final_total = max(total_subtotal - total_discount, Decimal("0"))
        grand_total = final_total + total_tax
        item_codes_str = ", ".join(item_codes) if item_codes else "No items"
        item_names_str = ", ".join(item_names) if item_names else "No items"

        customer_name = sale.customer_name or sale.customer_name_rel or "—"
        kode_lambung = sale.penjualan_kode_lambung or ""

        ws.append([
            sale.date.strftime("%d/%m/%Y") if sale.date else "",
            sale.sales_due_date.strftime("%d/%m/%Y") if sale.sales_due_date else "",
            customer_name,
            kode_lambung,
            sale.no_penjualan or "",
            (sale.status_pembayaran.name.capitalize() if hasattr(sale.status_pembayaran, "name")
             else str(sale.status_pembayaran)),
            item_codes_str,
            item_names_str,
            total_qty,
            float(total_subtotal / total_qty) if total_qty > 0 else 0.0,
            float(total_subtotal),
            float(final_total),
            float(total_tax),
            float(grand_total),
        ])

    # Save workbook to memory
    output = io.BytesIO()
    wb.save(output)
    output.seek(0)

    filename = f"laporan_penjualan_{from_date:%Y%m%d}_{to_date:%Y%m%d}.xlsx"

    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"'
        }
    )
@router.get("/pembelian")
async def get_pembelian_laporan(
    from_date: datetime = Query(...),
    to_date: Optional[datetime] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    """
    Returns one row per purchase with concatenated item details and aggregated totals.
    """
    if to_date is None:
        to_date = datetime.now()

    # Base query to get purchases
    purchases_query = (
        db.query(
            Pembelian.id,
            Pembelian.sales_date.label("date"),
            Pembelian.sales_due_date,
            Vendor.name.label("vendor_name_rel"),
            Pembelian.no_pembelian,
            Pembelian.status_pembayaran,
        )
        .join(Vendor, Vendor.id == Pembelian.vendor_id, isouter=True)
        .filter(
            Pembelian.is_deleted.is_(False),
            Pembelian.status_pembelian != StatusPembelianEnum.DRAFT,
            Pembelian.sales_date >= from_date.date(),
            Pembelian.sales_date <= to_date.date(),
        )
        .order_by(Pembelian.sales_date.asc(), Pembelian.no_pembelian.asc())
    )

    # Get total count
    total_count = purchases_query.count()

    # Get paginated purchases
    purchases = purchases_query.offset(skip).limit(limit).all()

    def _dec(x) -> Decimal:
        return Decimal(str(x or 0))

    report_rows: List[PurchaseReportRow] = []
    
    for purchase in purchases:
        # Get all items for this purchase with proper Item.name
        items_query = (
            db.query(
                Item.sku.label("item_sku"),
                Item.name.label("item_name"),
                Item.code.label("item_code"),
            
                PembelianItem.qty,
                PembelianItem.unit_price,
                PembelianItem.discount,
                PembelianItem.tax_percentage,
            )
            .join(Item, Item.id == PembelianItem.item_id, isouter=True)
            .filter(PembelianItem.pembelian_id == purchase.id)
            .all()
        )

        # Concatenate item details and calculate totals
        item_codes = []
        item_names = []  # Separate list for item names
        total_subtotal = Decimal("0")
        total_discount = Decimal("0")
        total_tax = Decimal("0")
        total_qty = 0

        for item in items_query:
            # Build item detail strings
            item_code = item.item_code or item.item_sku or "N/A"
            # Use Item.name from the joined table
            item_name = item.item_name or "N/A"
            qty = int(item.qty or 0)
            
            item_codes.append(item_code)
            item_names.append(item_name)
            
            # Calculate totals
            price = _dec(item.unit_price)
            item_subtotal = price * qty
            item_discount = _dec(item.discount)
            item_total = item_subtotal - item_discount
            if item_total < 0:
                item_total = Decimal("0")
            
            tax_pct = Decimal(str(item.tax_percentage or 0))
            item_tax = (item_total * tax_pct / Decimal(100))
            
            total_subtotal += item_subtotal
            total_discount += item_discount
            total_tax += item_tax
            total_qty += qty

        # Join items with comma
        item_codes_str = ", ".join(item_codes) if item_codes else "No items"
        item_names_str = ", ".join(item_names) if item_names else "No items"
        
        # Calculate final totals
        final_total = total_subtotal - total_discount
        if final_total < 0:
            final_total = Decimal("0")
        grand_total = final_total + total_tax

        report_rows.append(
            PurchaseReportRow(
                date=purchase.date,
                sales_due_date = purchase.sales_due_date,
                vendor=purchase.vendor_name_rel or "—",
                no_pembelian=purchase.no_pembelian,
                status=(purchase.status_pembayaran.name.capitalize() if hasattr(purchase.status_pembayaran, "name")
                        else str(purchase.status_pembayaran)),
                item_code=item_codes_str,  # Concatenated item codes
                item_name=item_names_str,  # Concatenated actual item names from Item.name
                qty=total_qty,
                price=total_subtotal / total_qty if total_qty > 0 else Decimal("0"),  # Average price
                sub_total=total_subtotal,
                total=final_total,
                tax=total_tax,
                grand_total=grand_total,
            )
        )

    title = f"Laporan Pembelian {from_date:%d/%m/%Y} - {to_date:%d/%m/%Y}"
    return PurchaseReportResponse(
        title=title,
        date_from=from_date,
        date_to=to_date,
        data=report_rows,
        total=total_count,
    )

@router.get(
    "/pembelian/download",
    status_code=status.HTTP_200_OK,
    summary="Download Laporan Pembelian as XLSX (all records)",
)
async def download_pembelian_laporan(
    from_date: datetime = Query(..., description="Start datetime (inclusive)"),
    to_date: datetime | None = Query(None, description="End datetime (inclusive)"),
    db: Session = Depends(get_db),
):
    if to_date is None:
        to_date = datetime.now()

    purchases_query = (
        db.query(
            Pembelian.id,
            Pembelian.sales_date.label("date"),
            Pembelian.sales_due_date,
            Vendor.name.label("vendor_name_rel"),
            Pembelian.no_pembelian,
            Pembelian.status_pembayaran,
        )
        .join(Vendor, Vendor.id == Pembelian.vendor_id, isouter=True)
        .filter(
            Pembelian.is_deleted.is_(False),
            Pembelian.status_pembelian != StatusPembelianEnum.DRAFT,
            Pembelian.sales_date >= from_date.date(),
            Pembelian.sales_date <= to_date.date(),
        )
        .order_by(Pembelian.sales_date.asc(), Pembelian.no_pembelian.asc())
    )

    purchases = purchases_query.all()

    def _dec(x) -> Decimal:
        return Decimal(str(x or 0))

    # Create Excel workbook and sheet
    wb = Workbook()
    ws = wb.active
    ws.title = "Laporan Pembelian"

    # Write header
    ws.append([
        'Date', 'Due Date', 'Vendor', 'No Pembelian', 'Status',
        'Item Code', 'Item Name', 'Qty', 'Price', 'Sub Total',
        'Total', 'Tax', 'Grand Total'
    ])

    for purchase in purchases:
        items_query = (
            db.query(
                Item.sku.label("item_sku"),
                Item.name.label("item_name"),
                Item.code.label("item_code"),
                PembelianItem.qty,
                PembelianItem.unit_price,
                PembelianItem.discount,
                PembelianItem.tax_percentage,
            )
            .join(Item, Item.id == PembelianItem.item_id, isouter=True)
            .filter(PembelianItem.pembelian_id == purchase.id)
            .all()
        )

        item_codes, item_names = [], []
        total_subtotal, total_discount, total_tax = Decimal("0"), Decimal("0"), Decimal("0")
        total_qty = 0

        for item in items_query:
            item_code = item.item_code or item.item_sku or "N/A"
            item_name = item.item_name or "N/A"
            qty = int(item.qty or 0)

            item_codes.append(item_code)
            item_names.append(item_name)

            price = _dec(item.unit_price)
            item_subtotal = price * qty
            item_discount = _dec(item.discount)
            item_total = max(item_subtotal - item_discount, Decimal("0"))
            tax_pct = Decimal(str(item.tax_percentage or 0))
            item_tax = item_total * tax_pct / Decimal(100)

            total_subtotal += item_subtotal
            total_discount += item_discount
            total_tax += item_tax
            total_qty += qty

        item_codes_str = ", ".join(item_codes) if item_codes else "No items"
        item_names_str = ", ".join(item_names) if item_names else "No items"
        final_total = max(total_subtotal - total_discount, Decimal("0"))
        grand_total = final_total + total_tax

        ws.append([
            purchase.date.strftime('%d/%m/%Y') if purchase.date else '',
            purchase.sales_due_date.strftime('%d/%m/%Y') if purchase.sales_due_date else '',
            purchase.vendor_name_rel or "—",
            purchase.no_pembelian or '',
            (purchase.status_pembayaran.name.capitalize() if hasattr(purchase.status_pembayaran, "name")
             else str(purchase.status_pembayaran)),
            item_codes_str,
            item_names_str,
            total_qty,
            float(total_subtotal / total_qty) if total_qty > 0 else 0.0,
            float(total_subtotal),
            float(final_total),
            float(total_tax),
            float(grand_total),
        ])

    # Save workbook to bytes
    output = io.BytesIO()
    wb.save(output)
    output.seek(0)

    filename = f"laporan_pembelian_{from_date:%Y%m%d}_{to_date:%Y%m%d}.xlsx"

    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"'
        }
    )
@router.get("/tren-penjualan", response_model=SalesTrendResponse)
async def get_sales_trend(
        period: str = Query(
            "mtd",
            regex="^(daily|mtd|custom)$",
            description="Period: 'daily' (last 30 days), 'mtd' (month to date), 'custom' (requires from_date and to_date)"
        ),
        from_date: Optional[datetime] = Query(None, description="Start date for custom period"),
        to_date: Optional[datetime] = Query(None, description="End date for custom period"),
        db: Session = Depends(get_db)
):
    """
    Get sales trend data showing daily order count and revenue.

    - **daily**: Last 30 days from today
    - **mtd**: Month to date (from 1st of current month to today)
    - **custom**: Custom date range (requires from_date and to_date)
    """

    now = datetime.now()

    # Determine date range based on period
    if period == "daily":
        start_date = (now - timedelta(days=30)).replace(hour=0, minute=0, second=0, microsecond=0)
        end_date = now.replace(hour=23, minute=59, second=59, microsecond=999999)
        title = "Tren Penjualan - 30 Hari Terakhir"

    elif period == "mtd":
        start_date = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        end_date = now.replace(hour=23, minute=59, second=59, microsecond=999999)
        title = f"Tren Penjualan - Month to Date ({start_date.strftime('%B %Y')})"

    elif period == "custom":
        if not from_date or not to_date:
            raise HTTPException(
                status_code=400,
                detail="from_date and to_date are required for custom period"
            )
        start_date = from_date.replace(hour=0, minute=0, second=0, microsecond=0)
        end_date = to_date.replace(hour=23, minute=59, second=59, microsecond=999999)
        title = f"Tren Penjualan - {start_date.strftime('%d/%m/%Y')} s/d {end_date.strftime('%d/%m/%Y')}"

    # Query to get daily sales data
    daily_sales = (
        db.query(
            func.date(Penjualan.sales_date).label('sale_date'),
            func.count(Penjualan.id).label('order_count'),
            func.coalesce(func.sum(Penjualan.total_price), 0).label('revenue')
        )
        .filter(
            Penjualan.is_deleted == False,
            Penjualan.status_penjualan != StatusPembelianEnum.DRAFT,
            Penjualan.sales_date >= start_date,
            Penjualan.sales_date <= end_date,
            Penjualan.sales_date.isnot(None)  # Exclude null dates
        )
        .group_by(func.date(Penjualan.sales_date))
        .order_by(func.date(Penjualan.sales_date))
        .all()
    )

    # Convert to response format
    trend_data = []
    total_orders = 0
    total_revenue = Decimal('0')

    for sale_data in daily_sales:
        # Convert date to datetime for consistent response
        sale_datetime = datetime.combine(sale_data.sale_date, datetime.min.time())
        revenue = Decimal(str(sale_data.revenue or 0))

        trend_data.append(SalesTrendDataPoint(
            date=sale_datetime,
            order_count=sale_data.order_count,
            revenue=revenue
        ))

        total_orders += sale_data.order_count
        total_revenue += revenue

    # Fill missing dates with zero values (optional - for complete timeline)
    if period in ["daily", "mtd"]:
        # Create a complete date range
        current_date = start_date.date()
        end_date_only = end_date.date()
        existing_dates = {dp.date.date() for dp in trend_data}

        complete_data = []
        while current_date <= end_date_only:
            if current_date in existing_dates:
                # Find existing data point
                existing_point = next(dp for dp in trend_data if dp.date.date() == current_date)
                complete_data.append(existing_point)
            else:
                # Add zero data point for missing dates
                complete_data.append(SalesTrendDataPoint(
                    date=datetime.combine(current_date, datetime.min.time()),
                    order_count=0,
                    revenue=Decimal('0')
                ))
            current_date += timedelta(days=1)

        trend_data = complete_data

    return SalesTrendResponse(
        title=title,
        period=period,
        data=trend_data,
        total_orders=total_orders,
        total_revenue=total_revenue
    )



def calculate_hpp(prev_balance: Decimal, prev_hpp: Decimal, qty_in: int, price_in: Decimal) -> Decimal:
    """
    Calculate HPP using weighted average formula: ((prev_balance * prev_hpp) + (qty_in * price_in)) / (prev_balance + qty_in)
    """
    if prev_balance + qty_in == 0:
        return Decimal("0")
    
    total_value = (prev_balance * prev_hpp) + (qty_in * price_in)
    total_qty = prev_balance + qty_in
    
    return total_value / total_qty

@router.get(
    "/stock-adjustment",
    status_code=status.HTTP_200_OK,
    response_model=StockAdjustmentReportResponse,
)
async def get_stock_adjustment_report(
    from_date: datetime = Query(..., description="Start datetime (inclusive)"),
    to_date: Optional[datetime] = Query(None, description="End datetime (inclusive)"),
    item_id: Optional[int] = Query(None, description="Filter by specific item"),
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of records to return"),
    db: Session = Depends(get_db),
):
    """
    Get stock adjustment report with HPP calculation from InventoryLedger.
    Returns grouped data by item name.
    """

    if to_date is None:
        to_date = datetime.now()

    from_date_only = from_date.date()
    to_date_only = to_date.date()

    # Base query
    query = (
        db.query(
            InventoryLedger.trx_date,
            InventoryLedger.source_type,
            InventoryLedger.source_id,
            InventoryLedger.qty_in,
            InventoryLedger.qty_out,
            InventoryLedger.unit_price,
            InventoryLedger.cumulative_qty,
            InventoryLedger.moving_avg_cost,
            Item.code.label("item_code"),
            Item.name.label("item_name"),
        )
        .join(Item, Item.id == InventoryLedger.item_id)
        .filter(
            InventoryLedger.voided.is_(False),
            InventoryLedger.trx_date >= from_date_only,
            InventoryLedger.trx_date <= to_date_only,
        )
        .order_by(Item.name.asc(), InventoryLedger.trx_date.desc())
    )

    # Apply optional filter
    if item_id is not None:
        query = query.filter(InventoryLedger.item_id == item_id)

    # Total before pagination
    total_count = query.count()

    # Paginate
    ledger_entries = query.offset(skip).limit(limit).all()

    # ----------------------------
    # Group by item_name
    # ----------------------------
    grouped_data: dict[str, List[StockAdjustmentReportRow]] = {}

    for entry in ledger_entries:
        trans_no = entry.source_id or ""
        price_in = entry.unit_price if entry.qty_in > 0 else Decimal("0")
        price_out = entry.unit_price if entry.qty_out > 0 else Decimal("0")

        row = StockAdjustmentReportRow(
            date=datetime.combine(entry.trx_date, datetime.min.time()),
            no_transaksi=trans_no,
            item_code=entry.item_code or "N/A",
            item_name=entry.item_name or "N/A",
            qty_masuk=entry.qty_in,
            qty_keluar=entry.qty_out,
            qty_balance=entry.cumulative_qty,
            harga_masuk=price_in,
            harga_keluar=price_out,
            hpp=entry.moving_avg_cost,
        )

        grouped_data.setdefault(entry.item_name or "N/A", []).append(row)

    # Convert to list of ItemStockAdjustmentReportRow
    grouped_rows: List[ItemStockAdjustmentReportRow] = [
        ItemStockAdjustmentReportRow(item_name=item, data=rows)
        for item, rows in grouped_data.items()
    ]

    title = f"Laporan Stock Adjustment {from_date:%d/%m/%Y} - {to_date:%d/%m/%Y}"

    return StockAdjustmentReportResponse(
        title=title,
        date_from=from_date,
        date_to=to_date,
        data=grouped_rows,
        total=total_count,
    )

@router.get(
    "/stock-adjustment/download",
    status_code=status.HTTP_200_OK,
    summary="Download Stock Adjustment Report as XLSX (all records)",
)
async def download_stock_adjustment_report(
    from_date: datetime = Query(..., description="Start datetime (inclusive)"),
    to_date: datetime | None = Query(None, description="End datetime (inclusive)"),
    item_id: int | None = Query(None, description="Filter by specific item"),
    db: Session = Depends(get_db),
):
    """
    Download complete stock adjustment report as XLSX without pagination.
    """

    if to_date is None:
        to_date = datetime.now()

    # Convert datetime to date for querying
    from_date_only = from_date.date()
    to_date_only = to_date.date()

    # Base query
    query = (
        db.query(
            InventoryLedger.trx_date,
            InventoryLedger.source_type,
            InventoryLedger.source_id,
            InventoryLedger.qty_in,
            InventoryLedger.qty_out,
            InventoryLedger.unit_price,
            InventoryLedger.cumulative_qty,
            InventoryLedger.moving_avg_cost,
            Item.code.label("item_code"),
            Item.name.label("item_name"),
        )
        .join(Item, Item.id == InventoryLedger.item_id)
        .filter(
            InventoryLedger.voided.is_(False),
            InventoryLedger.trx_date >= from_date_only,
            InventoryLedger.trx_date <= to_date_only,
        )
        .order_by(Item.name.asc(), InventoryLedger.trx_date.desc())
    )

    # Apply filter
    if item_id is not None:
        query = query.filter(InventoryLedger.item_id == item_id)

    ledger_entries = query.all()

    # Create workbook
    wb = Workbook()
    ws = wb.active
    ws.title = "Stock Adjustment"

    # Write header row
    headers = [
        "Date",
        "No Transaksi",
        "Item Code",
        "Item Name",
        "Qty Masuk",
        "Qty Keluar",
        "Qty Balance",
        "Harga Masuk",
        "Harga Keluar",
        "HPP",
    ]
    ws.append(headers)

    # Write rows
    for entry in ledger_entries:
        trans_no = entry.source_id or ""
        price_in = entry.unit_price if entry.qty_in > 0 else Decimal("0")
        price_out = entry.unit_price if entry.qty_out > 0 else Decimal("0")
        date_str = entry.trx_date.strftime("%d/%m/%Y")

        ws.append([
            date_str,
            trans_no,
            entry.item_code or "N/A",
            entry.item_name or "N/A",
            float(entry.qty_in or 0),
            float(entry.qty_out or 0),
            float(entry.cumulative_qty or 0),
            float(price_in),
            float(price_out),
            float(entry.moving_avg_cost or 0),
        ])

    # Optional: auto-adjust column widths (just for readability)
    for col in ws.columns:
        max_length = max(len(str(cell.value or "")) for cell in col)
        ws.column_dimensions[col[0].column_letter].width = min(max_length + 2, 40)

    # Save workbook in-memory
    output = io.BytesIO()
    wb.save(output)
    output.seek(0)

    filename = f"laporan_stock_adjustment_{from_date:%Y%m%d}_{to_date:%Y%m%d}.xlsx"

    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"'
        },
    )