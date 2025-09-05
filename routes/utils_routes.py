import csv
from datetime import timedelta, datetime
from decimal import Decimal
import io
from typing import List, Optional

from fastapi import FastAPI,  APIRouter

from fastapi.params import Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import extract, func
from sqlalchemy.orm import Session
from starlette import status

from starlette.exceptions import HTTPException

from models.Customer import Customer
from models.Item import Item
from models.Pembelian import Pembelian, PembelianItem, StatusPembelianEnum
from models.Penjualan import Penjualan, PenjualanItem
from models.Vendor import Vendor
from schemas.PaginatedResponseSchemas import PaginatedResponse
from schemas.UserSchemas import UserCreate, TokenSchema, RequestDetails, UserOut, UserUpdate, UserType
from database import  get_db
from schemas.UtilsSchemas import DashboardStatistics, LabaRugiResponse, PurchaseReportResponse, PurchaseReportRow, SalesReportRow, SalesReportResponse
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
    total_products = db.query(Item).count()
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
    total_customer = db.query(Customer).count()
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
    "/penjualan",
    status_code=status.HTTP_200_OK,
    response_model=PaginatedResponse[SalesReportRow],
    summary="Laporan Penjualan (consolidated per sale)",
)
async def get_penjualan_laporan(
        from_date: datetime = Query(..., description="Start datetime (inclusive)"),
        to_date: Optional[datetime] = Query(None, description="End datetime (inclusive)"),
        skip: int = Query(0, ge=0, description="Number of records to skip"),
        limit: int = Query(100, ge=1, le=1000, description="Maximum number of records to return"),
        db: Session = Depends(get_db),
):
    """
    Returns one row per sale with concatenated item details and aggregated totals.
    """

    if to_date is None:
        to_date = datetime.now()

    # Base query to get sales
    sales_query = (
        db.query(
            Penjualan.id,
            Penjualan.sales_date.label("date"),
            Penjualan.customer_name.label("customer_name_stored"),
            Customer.name.label("customer_name_rel"),
            Customer.kode_lambung,
            Penjualan.no_penjualan,
            Penjualan.status_pembayaran,
        )
        .join(Customer, Customer.id == Penjualan.customer_id, isouter=True)
        .filter(
            Penjualan.is_deleted.is_(False),
            Penjualan.status_penjualan != StatusPembelianEnum.DRAFT,
            Penjualan.sales_date >= from_date.date(),
            Penjualan.sales_date <= to_date.date(),
        )
        .order_by(Penjualan.sales_date.asc(), Penjualan.no_penjualan.asc())
    )

    # Get total count
    total_count = sales_query.count()

    # Get paginated sales
    sales = sales_query.offset(skip).limit(limit).all()

    def _dec(x) -> Decimal:
        return Decimal(str(x or 0))

    report_rows: List[SalesReportRow] = []
    
    for sale in sales:
        # Get all items for this sale
        items_query = (
            db.query(
                PenjualanItem.item_sku,
                PenjualanItem.item_name,
                PenjualanItem.qty,
                PenjualanItem.unit_price,
                PenjualanItem.discount,
                PenjualanItem.tax_percentage,
                Item.code.label("item_code")
            )
            .join(Item, Item.id == PenjualanItem.item_id, isouter=True)
            .filter(PenjualanItem.penjualan_id == sale.id)
            .all()
        )

        # Concatenate item details and calculate totals
        item_details = []
        total_subtotal = Decimal("0")
        total_discount = Decimal("0")
        total_tax = Decimal("0")
        total_qty = 0

        for item in items_query:
            # Build item detail string
            item_code = item.item_code or item.item_sku or "N/A"
            item_name = item.item_name or "N/A"
            qty = int(item.qty or 0)
            
            item_details.append(f"{item_code} - {item_name}")
            
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
        items_str = ", ".join(item_details) if item_details else "No items"
        
        # Calculate final totals
        final_total = total_subtotal - total_discount
        if final_total < 0:
            final_total = Decimal("0")
        grand_total = final_total + total_tax

        report_rows.append(
            SalesReportRow(
                date=sale.date,
                customer=sale.customer_name_stored or sale.customer_name_rel or "—",
                kode_lambung=getattr(sale, "kode_lambung", None),
                no_penjualan=sale.no_penjualan,
                status=(sale.status_pembayaran.name.capitalize() if hasattr(sale.status_pembayaran, "name")
                        else str(sale.status_pembayaran)),
                item_code=items_str,  # Use concatenated items instead of single item_code
                item_name=f"{len(item_details)} items (Total Qty: {total_qty})",  # Summary instead of single item_name
                qty=total_qty,
                price=total_subtotal / total_qty if total_qty > 0 else Decimal("0"),  # Average price
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
            Pembelian.sales_date.label("date"),  # Keep as sales_date since that's your schema
            Pembelian.vendor_name.label("vendor_name_stored"),
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
        # Get all items for this purchase
        items_query = (
            db.query(
                PembelianItem.item_sku,
                PembelianItem.item_name,
                PembelianItem.qty,
                PembelianItem.unit_price,
                PembelianItem.discount,
                PembelianItem.tax_percentage,
                Item.code.label("item_code")
            )
            .join(Item, Item.id == PembelianItem.item_id, isouter=True)
            .filter(PembelianItem.pembelian_id == purchase.id)
            .all()
        )

        # Concatenate item details and calculate totals
        item_details = []
        total_subtotal = Decimal("0")
        total_discount = Decimal("0")
        total_tax = Decimal("0")
        total_qty = 0

        for item in items_query:
            # Build item detail string
            item_code = item.item_code or item.item_sku or "N/A"
            item_name = item.item_name or "N/A"
            qty = int(item.qty or 0)
            
            item_details.append(f"{item_code} - {item_name}")
            
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
        items_str = ", ".join(item_details) if item_details else "No items"
        
        # Calculate final totals
        final_total = total_subtotal - total_discount
        if final_total < 0:
            final_total = Decimal("0")
        grand_total = final_total + total_tax

        report_rows.append(
            PurchaseReportRow(
                date=purchase.date,
                vendor=purchase.vendor_name_stored or purchase.vendor_name_rel or "—",
                no_pembelian=purchase.no_pembelian,
                status=(purchase.status_pembayaran.name.capitalize() if hasattr(purchase.status_pembayaran, "name")
                        else str(purchase.status_pembayaran)),
                item_code=items_str,  # Use concatenated items instead of single item_code
                item_name=f"{len(item_details)} items (Total Qty: {total_qty})",  # Summary instead of single item_name
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
    "/penjualan/download",
    status_code=status.HTTP_200_OK,
    summary="Download Laporan Penjualan as CSV (all records)",
)
async def download_penjualan_laporan(
        from_date: datetime = Query(..., description="Start datetime (inclusive)"),
        to_date: Optional[datetime] = Query(None, description="End datetime (inclusive)"),
        db: Session = Depends(get_db),
):
    """
    Download complete sales report as CSV without pagination.
    Returns all records matching the date filter.
    """
    
    if to_date is None:
        to_date = datetime.now()

    # Query all records without pagination
    query = (
        db.query(
            Penjualan.sales_date.label("date"),
            Penjualan.customer_name.label("customer_name_stored"),
            Customer.name.label("customer_name_rel"),
            Customer.kode_lambung,
            Penjualan.no_penjualan,
            Penjualan.status_pembayaran,
            PenjualanItem.item_sku,
            PenjualanItem.item_name,
            PenjualanItem.qty,
            PenjualanItem.unit_price,
            PenjualanItem.discount,
            PenjualanItem.tax_percentage,
            Item.code.label("item_code") 
        )
        .join(Customer, Customer.id == Penjualan.customer_id, isouter=True)
        .join(PenjualanItem, PenjualanItem.penjualan_id == Penjualan.id)
        .filter(
            Penjualan.is_deleted.is_(False),
            Penjualan.status_penjualan != StatusPembelianEnum.DRAFT,
            Penjualan.sales_date >= from_date.date(),
            Penjualan.sales_date <= to_date.date(),
        )
        .order_by(Penjualan.sales_date.asc(), Penjualan.no_penjualan.asc(), PenjualanItem.id.asc())
    )

    rows = query.all()

    def _dec(x) -> Decimal:
        return Decimal(str(x or 0))

    # Create CSV content with proper encoding
    output = io.StringIO()
    writer = csv.writer(output, delimiter=';', quotechar='"', quoting=csv.QUOTE_MINIMAL)
    
    # Write header
    writer.writerow([
        'Date',
        'Customer',
        'Kode Lambung',
        'No Penjualan',
        'Status',
        'Item Code',
        'Item Name',
        'Qty',
        'Price',
        'Sub Total',
        'Total',
        'Tax',
        'Grand Total'
    ])

    # Write data rows
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

        writer.writerow([
            r.date.strftime('%d/%m/%Y') if r.date else '',
            r.customer_name_stored or r.customer_name_rel or "—",
            getattr(r, "kode_lambung", None) or '',
            r.no_penjualan or '',
            (r.status_pembayaran.name.capitalize() if hasattr(r.status_pembayaran, "name")
             else str(r.status_pembayaran)),
            r.item_code or '',
            r.item_name or '',
            str(qty),  # Convert to string to avoid formatting issues
            str(float(price)),
            str(float(sub_total)),
            str(float(total)),
            str(float(tax)),
            str(float(grand_total))
        ])

    # Get the CSV content
    csv_content = output.getvalue()
    output.close()
    
    # Generate filename
    filename = f"laporan_penjualan_{from_date:%Y%m%d}_{to_date:%Y%m%d}.csv"
    
    # Return as streaming response with proper headers
    return StreamingResponse(
        io.BytesIO(csv_content.encode('utf-8-sig')),  # Use UTF-8-sig for better Excel compatibility
        media_type="text/csv",  # Keep as text/csv
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Type": "text/csv; charset=utf-8"
        }
    )


@router.get(
    "/pembelian/download",
    status_code=status.HTTP_200_OK,
    summary="Download Laporan Pembelian as CSV (all records)",
)
async def download_pembelian_laporan(
        from_date: datetime = Query(..., description="Start datetime (inclusive)"),
        to_date: Optional[datetime] = Query(None, description="End datetime (inclusive)"),
        db: Session = Depends(get_db),
):
    """
    Download complete purchase report as CSV without pagination.
    Returns all records matching the date filter.
    """
    
    if to_date is None:
        to_date = datetime.now()

    # Query all records without pagination
    query = (
        db.query(
            Pembelian.sales_date.label("date"),
            Pembelian.vendor_name.label("vendor_name_stored"),
            Vendor.name.label("vendor_name_rel"),
            Pembelian.no_pembelian,
            Pembelian.status_pembayaran,
            PembelianItem.item_sku,
            PembelianItem.item_name,
            PembelianItem.qty,
            PembelianItem.unit_price,
            PembelianItem.discount,
            PembelianItem.tax_percentage,
        )
        .join(Vendor, Vendor.id == Pembelian.vendor_id, isouter=True)
        .join(PembelianItem, PembelianItem.pembelian_id == Pembelian.id)
        .filter(
            Pembelian.is_deleted.is_(False),
            Pembelian.status_pembelian != StatusPembelianEnum.DRAFT,
            Pembelian.sales_date >= from_date.date(),
            Pembelian.sales_date <= to_date.date(),
        )
        .order_by(Pembelian.sales_date.asc(), Pembelian.no_pembelian.asc(), PembelianItem.id.asc())
    )

    rows = query.all()

    def _dec(x) -> Decimal:
        return Decimal(str(x or 0))

    # Create CSV content with proper encoding
    output = io.StringIO()
    writer = csv.writer(output, delimiter=';', quotechar='"', quoting=csv.QUOTE_MINIMAL)
    
    # Write header
    writer.writerow([
        'Date',
        'Vendor',
        'No Pembelian',
        'Status',
        'Item Code',
        'Item Name',
        'Qty',
        'Price',
        'Sub Total',
        'Total',
        'Tax',
        'Grand Total'
    ])

    # Write data rows
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

        writer.writerow([
            r.date.strftime('%d/%m/%Y') if r.date else '',
            r.vendor_name_stored or r.vendor_name_rel or "—",
            r.no_pembelian or '',
            (r.status_pembayaran.name.capitalize() if hasattr(r.status_pembayaran, "name")
             else str(r.status_pembayaran)),
            r.item_sku or '',
            r.item_name or '',
            str(qty),  # Convert to string to avoid formatting issues
            str(float(price)),
            str(float(sub_total)),
            str(float(total)),
            str(float(tax)),
            str(float(grand_total))
        ])

    # Get the CSV content
    csv_content = output.getvalue()
    output.close()
    
    # Generate filename
    filename = f"laporan_pembelian_{from_date:%Y%m%d}_{to_date:%Y%m%d}.csv"
    
    # Return as streaming response with proper headers
    return StreamingResponse(
        io.BytesIO(csv_content.encode('utf-8-sig')),  # Use UTF-8-sig for better Excel compatibility
        media_type="text/csv",  # Keep as text/csv
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Type": "text/csv; charset=utf-8"
        }
    )
    

