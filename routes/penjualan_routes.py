import base64
import random

from fastapi import APIRouter, Depends, HTTPException, File, UploadFile, Query, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session, selectinload, joinedload
from sqlalchemy import and_, func, desc, cast, Integer
from typing import List, Optional
import uuid
import os
import shutil
import enum
from datetime import datetime, time, date
from decimal import Decimal, InvalidOperation

from starlette.requests import Request
from starlette.responses import HTMLResponse

from database import get_db
from models.AuditTrail import AuditEntityEnum
from models.Customer import Customer
from models.InventoryLedger import SourceTypeEnum
from models.KodeLambung import KodeLambung
from models.Pembayaran import  Pembayaran
from models.Penjualan import StatusPembayaranEnum, StatusPembelianEnum
from models.Penjualan import Penjualan, PenjualanItem

from models.Item import Item

from models.AllAttachment import ParentType, AllAttachment
from routes.upload_routes import get_public_image_url, to_public_image_url, templates
from schemas.PaginatedResponseSchemas import PaginatedResponse
from schemas.PenjualanSchema import PenjualanCreate, PenjualanListResponse, PenjualanResponse, PenjualanStatusUpdate, PenjualanUpdate, SuccessResponse, TotalsResponse, UploadResponse
from services.audit_services import AuditService
from services.fifo_services import FifoService
from services.inventoryledger_services import InventoryService
from utils import generate_unique_record_number, get_current_user_name
from decimal import Decimal, InvalidOperation  # add InvalidOperation

router = APIRouter()

# Configuration
UPLOAD_DIR = os.getenv("STATIC_URL")
os.makedirs(UPLOAD_DIR, exist_ok=True)
ALLOWED_FILE_TYPES = ["application/pdf", "image/jpeg", "image/png", "image/jpg"]
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB
def calculate_item_totals(item: PenjualanItem) -> None:
    """
    Calculate item totals following the exact frontend logic:
    1. rowSubTotal = unit * qty (pre-discount, pre-tax)
    2. taxableBase = max(rowSubTotal - discount, 0)
    3. rowTax = (taxableBase * taxPct) / 100
    4. rowTotal = taxableBase + rowTax
    """
    qty = Decimal(str(item.qty or 0))
    unit_price = Decimal(str(item.unit_price or 0))
    tax_percentage = Decimal(str(item.tax_percentage or 0))
    discount = Decimal(str(item.discount or 0))

    # Frontend logic: rowSubTotal = unit * qty
    row_sub_total = qty * unit_price
    
    # Frontend logic: taxableBase = max(rowSubTotal - discount, 0)
    taxable_base = max(row_sub_total - discount, Decimal('0'))
    
    # Frontend logic: rowTax = (taxableBase * taxPct) / 100
    row_tax = (taxable_base * tax_percentage) / Decimal('100')
    
    # Frontend logic: rowTotal = taxableBase + rowTax
    row_total = taxable_base + row_tax

    # Store calculated values
    item.sub_total = row_sub_total  # This is rowSubTotal in frontend
    item.total_price = row_total    # This is rowTotal in frontend
    
    # For compatibility - price_after_tax as unit equivalent
    item.price_after_tax = (row_total / qty) if qty > 0 else Decimal('0')


def calculate_penjualan_totals(db: Session, penjualan_id: int, msg : str, user_name : str = "" ):
    """
    Calculate penjualan totals following the exact frontend logic
    """
    audit_service = AuditService(db)
    items = db.query(PenjualanItem).filter(PenjualanItem.penjualan_id == penjualan_id).all()

    # Recalculate each item first
    for item in items:
        calculate_item_totals(item)

    # Frontend variables
    sub_total = Decimal('0')  # sum of all rowSubTotal
    total_item_discounts = Decimal('0')  # sum of all item discounts
    total_tax = Decimal('0')  # sum of all rowTax
    grand_total_items = Decimal('0')  # sum of all rowTotal

    # Calculate row-level totals
    for item in items:
        qty = Decimal(str(item.qty or 0))
        unit_price = Decimal(str(item.unit_price or 0))
        tax_percentage = Decimal(str(item.tax_percentage or 0))
        discount = Decimal(str(item.discount or 0))

        # Replicate frontend row calculations exactly
        row_sub_total = unit_price * qty
        taxable_base = max(row_sub_total - discount, Decimal('0'))
        row_tax = (taxable_base * tax_percentage) / Decimal('100')
        row_total = taxable_base + row_tax

        # Accumulate totals
        sub_total += row_sub_total
        total_item_discounts += discount
        total_tax += row_tax
        grand_total_items += row_total

    # Get penjualan for additional fields
    penjualan = db.query(Penjualan).filter(Penjualan.id == penjualan_id).first()
    if not penjualan:
        raise HTTPException(status_code=404, detail="Penjualan not found")

    additional_discount = Decimal(str(penjualan.additional_discount or 0))
    expense = Decimal(str(penjualan.expense or 0))

    # Frontend calculation logic
    subtotal_after_item_discounts = max(sub_total - total_item_discounts, Decimal('0'))
    final_total_before_tax = max(subtotal_after_item_discounts - additional_discount, Decimal('0'))
    total = max(sub_total - total_item_discounts, Decimal('0'))  # This is 'total' in frontend
    grand_total = final_total_before_tax + total_tax + expense

    # Update penjualan with calculated values
    penjualan.total_subtotal = sub_total  # This is subTotal in frontend
    penjualan.total_discount = total_item_discounts  # This is totalItemDiscounts in frontend
    penjualan.additional_discount = additional_discount
    penjualan.total_before_discount = final_total_before_tax  # This is finalTotalBeforeTax in frontend
    penjualan.total_tax = total_tax  # This is totalTax in frontend
    penjualan.expense = expense
    penjualan.total_price = grand_total  # This is grandTotal in frontend
    penjualan.total_qty = sum(int(it.qty or 0) for it in items)

    if (msg !=  "" or msg != None) :
        audit_service.default_log(
            entity_id=penjualan.id,
            entity_type=AuditEntityEnum.PENJUALAN,
            description=f"Penjualan {penjualan.no_penjualan} {msg} : Total Rp{grand_total:.4f} ",
            user_name=user_name
        )

    db.commit()

    return {
        "total_subtotal": sub_total,  # subTotal in frontend
        "total_discount": total_item_discounts,  # totalItemDiscounts in frontend
        "additional_discount": additional_discount,
        "total_before_discount": final_total_before_tax,  # finalTotalBeforeTax in frontend
        "total_tax": total_tax,  # totalTax in frontend
        "expense": expense,
        "total_price": grand_total,  # grandTotal in frontend
        "total_qty": penjualan.total_qty,
        "total_grand_total_items": grand_total_items,  # grandTotalItems in frontend
        "subtotal_after_item_discounts": subtotal_after_item_discounts,  # For debugging
        "total": total,  # 'total' variable in frontend
    }



def calculate_template_totals(penjualan, enhanced_items):
    """
    Calculate totals for the HTML template following frontend logic
    """
    subtotal_before_discount = Decimal('0')  # Sum of all rowSubTotal
    total_item_discounts = Decimal('0')      # Sum of all item discounts
    tax_amount = Decimal('0')                # Sum of all rowTax
    
    for item_data in enhanced_items:
        # These should already be calculated correctly if using the fixed calculate_item_totals
        subtotal_before_discount += item_data["item_subtotal_before_discount"]
        total_item_discounts += item_data["item_discount"]
        tax_amount += item_data["item_tax"]

    # Additional totals
    additional_discount = Decimal(str(penjualan.additional_discount or 0))
    expense = Decimal(str(penjualan.expense or 0))
    
    # Calculate intermediate values following frontend logic
    subtotal_after_item_discounts = max(subtotal_before_discount - total_item_discounts, Decimal('0'))
    final_total_before_tax = max(subtotal_after_item_discounts - additional_discount, Decimal('0'))
    grand_total = final_total_before_tax + tax_amount + expense

    return {
        "subtotal": subtotal_before_discount,           # subTotal in frontend
        "item_discounts": total_item_discounts,         # totalItemDiscounts in frontend  
        "additional_discount": additional_discount,     
        "subtotal_after_discounts": subtotal_after_item_discounts,  # subtotalAfterItemDiscounts in frontend
        "final_total": final_total_before_tax,          # finalTotalBeforeTax in frontend
        "tax_amount": tax_amount,                       # totalTax in frontend
        "expense": expense,
        "grand_total": grand_total,                     # grandTotal in frontend
        # Keep backward compatibility
        "total_item_discount": total_item_discounts,
    }


def validate_item_exists(db: Session, item_id: int) -> Item:
    item = db.query(Item).filter(Item.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail=f"Item with ID {item_id} not found")
    return item

def validate_item_stock(db: Session, item_id: int, requested_qty: int, warehouse_id: Optional[int] = None) -> None:
    """Ensure stock is sufficient based on FIFO batches."""
    from models.BatchStock import BatchStock
    from sqlalchemy import func, and_
    
    item_data = db.query(Item).filter(Item.id == item_id).first()
    
    if requested_qty < 1:
        raise HTTPException(status_code=400, detail="qty must be >= 1")

    # Calculate total available stock from open FIFO batches
    query = db.query(
        func.sum(BatchStock.sisa_qty).label('total_available')
    ).filter(
        and_(
            BatchStock.item_id == item_id,
            BatchStock.is_open == True,
            BatchStock.sisa_qty > 0
        )
    )
    
    # Filter by warehouse if specified
    if warehouse_id:
        query = query.filter(BatchStock.warehouse_id == warehouse_id)
    
    result = query.scalar()
    available = result if result else 0

    if available < requested_qty:
        raise HTTPException(
            status_code=400,
            detail=f"Stock untuk item {item_data.name} tidak tersedia. "
                   f"Tersedia: {available}, Requested: {requested_qty}"
        )


def update_item_stock(db: Session, item_id: int, qty_change: int) -> None:
    """
    SALES direction: negative change reduces stock, positive change returns stock.
    """
    item = validate_item_exists(db, item_id)
    if item.total_item is None:
        item.total_item = 0
    # Apply change but never let it drop below zero
    new_total = int(item.total_item) + int(qty_change)
    if new_total < 0:
        raise HTTPException(
            status_code=400,
            detail=f"Stock akan menjadi < 0 untuk item '{item.name}'. "
                   f"Current: {item.total_item}, Change: {qty_change}"
        )
    item.total_item = new_total

def finalize_penjualan(db: Session, penjualan_id: int, user_name: str) -> None:
    """
    Finalize SALES using FIFO:
      - Validate required fields
      - Validate stock availability per line using FIFO batches
      - Process sale through FIFO (consumes oldest batches first)
      - Snapshot friendly names
      - Set status ACTIVE
    """
    audit_service = AuditService(db)
    
    penjualan = (
        db.query(Penjualan)
        .options(
            selectinload(Penjualan.warehouse_rel),
            selectinload(Penjualan.customer_rel).selectinload("*"),
            selectinload(Penjualan.top_rel),
            selectinload(Penjualan.penjualan_items).selectinload(PenjualanItem.item_rel),
        )
        .filter(Penjualan.id == penjualan_id)
        .first()
    )

    if not penjualan:
        raise HTTPException(status_code=404, detail="Penjualan not found")

    if penjualan.status_penjualan != StatusPembelianEnum.DRAFT:
        raise HTTPException(status_code=400, detail="Can only finalize DRAFT penjualans")

    if not penjualan.warehouse_id or not penjualan.customer_id:
        raise HTTPException(status_code=400, detail="Warehouse and Customer are required for finalization")

    if not penjualan.penjualan_items:
        raise HTTPException(status_code=400, detail="At least one item is required for finalization")

    # 1) Validate stock for ALL items FIRST - collect all errors before proceeding
    validation_errors = []
    for line in penjualan.penjualan_items:
        try:
            validate_item_stock(db, line.item_id, line.qty, penjualan.warehouse_id)
        except HTTPException as e:
            item_name = line.item_rel.name if line.item_rel else f"ID {line.item_id}"
            validation_errors.append(f"{item_name}: {e.detail}")
    
    # If ANY validation failed, raise error WITHOUT making any changes
    if validation_errors:
        raise HTTPException(
            status_code=400, 
            detail=f"Tidak dapat finalisasi - masalah stok: {'; '.join(validation_errors)}"
        )

    # 2) Snapshot names / metadata
    if penjualan.warehouse_rel:
        penjualan.warehouse_name = penjualan.warehouse_rel.name

    cust = penjualan.customer_rel
    if cust:
        penjualan.customer_name = getattr(cust, "name", None)
        penjualan.customer_address = getattr(cust, "address", None)
        if getattr(cust, "curr_rel", None):
            penjualan.currency_name = getattr(cust.curr_rel, "name", None)

    if penjualan.top_rel:
        penjualan.top_name = penjualan.top_rel.name

    # Get transaction date
    trx_date = penjualan.sales_date.date() if isinstance(penjualan.sales_date, datetime) else penjualan.sales_date

    # 3) NOW safe to process sales through FIFO - we know ALL items have sufficient stock
    for line in penjualan.penjualan_items:
        # Snapshot satuan name if needed
        if line.item_rel:
            item = line.item_rel
            if getattr(item, "satuan_rel", None):
                line.satuan_name = item.satuan_rel.name
        
        # Process sale using FIFO - this will consume from oldest batches
        try:
            total_hpp, fifo_logs = FifoService.process_sale_fifo(
                db=db,
                invoice_id=penjualan.no_penjualan,
                invoice_date=trx_date,
                item_id=line.item_id,
                qty_terjual=line.qty,
                harga_jual_per_unit=Decimal(str(line.unit_price)),
                warehouse_id=penjualan.warehouse_id
            )
            
            # Update item stock
            update_item_stock(db, line.item_id, -int(line.qty or 0))
            
        except ValueError as e:
            # This shouldn't happen since we validated, but handle it anyway
            raise HTTPException(
                status_code=400,
                detail=f"FIFO processing failed for item {line.item_id}: {str(e)}"
            )

    # 4) Activate
    penjualan.status_penjualan = StatusPembelianEnum.ACTIVE

    audit_service.default_log(
        entity_id=penjualan.id,
        entity_type=AuditEntityEnum.PENJUALAN,
        description=f"Penjualan {penjualan.no_penjualan} status transaksi diubah: Draft → Aktif",
        user_name=user_name
    )

    db.commit()

def validate_draft_status(penjualan: Penjualan):
    if penjualan.status_penjualan != StatusPembelianEnum.DRAFT:
        raise HTTPException(status_code=400, detail="Can only modify DRAFT penjualans")


def save_uploaded_file(file: UploadFile, penjualan_id: int) -> str:
    if file.size and file.size > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"File size too large. Maximum size is {MAX_FILE_SIZE // (1024*1024)}MB",
        )
    ext = os.path.splitext(file.filename or "")[1]
    unique = f"{penjualan_id}_{uuid.uuid4().hex[:8]}{ext}"
    path = os.path.join(UPLOAD_DIR, unique)
    with open(path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    return path


# ------------------------------
# Payload validators (mirror Pembelian’s)
# ------------------------------

def _get_item_id(obj):
    return getattr(obj, "item_id", None) if not isinstance(obj, dict) else obj.get("item_id")


def _normalize_item_payload(obj):
    data = obj if isinstance(obj, dict) else (obj.dict() if hasattr(obj, "dict") else obj.model_dump())
    try:
        qty = int(data.get("qty", 0))
        unit_price = Decimal(str(data.get("unit_price", "0")))
        tax_percentage = int(data.get("tax_percentage", 0) or 0)
        discount = Decimal(str(data.get("discount", "0") or 0))
    except (ValueError, InvalidOperation):
        raise HTTPException(status_code=400, detail="Invalid numeric values in items")

    return {
        "item_id": data.get("item_id"),
        "qty": qty,
        "unit_price": unit_price,
        "tax_percentage": tax_percentage,
        "discount": discount,
    }


def _validate_items_payload(items_data: List):
    seen = set()
    for idx, raw in enumerate(items_data or []):
        item_id = _get_item_id(raw)
        if not item_id:
            raise HTTPException(status_code=400, detail=f"items[{idx}]: item_id is required")
        if item_id in seen:
            raise HTTPException(status_code=400, detail=f"Duplicate item_id in payload: {item_id}")
        seen.add(item_id)

        d = _normalize_item_payload(raw)
        if d["qty"] < 1:
            raise HTTPException(status_code=400, detail=f"items[{idx}]: qty must be >= 1")
        if d["unit_price"] < 0:
            raise HTTPException(status_code=400, detail=f"items[{idx}]: unit_price must be >= 0")
        if not (0 <= d["tax_percentage"] <= 100):
            raise HTTPException(status_code=400, detail=f"items[{idx}]: tax_percentage must be between 0 and 100")
        max_discount = d["unit_price"] * d["qty"]
        if d["discount"] < 0 or d["discount"] > max_discount:
            raise HTTPException(
                status_code=400,
                detail=f"items[{idx}]: discount must be between 0 and qty*unit_price (<= {max_discount})",
            )


# ------------------------------
# API Endpoints
# ------------------------------
@router.get("", response_model=PaginatedResponse[PenjualanListResponse])
async def get_all_penjualan(
    status_penjualan: Optional[StatusPembelianEnum] = Query(None),
    status_pembayaran: Optional[StatusPembayaranEnum] = Query(None),
    customer_id: Optional[str] = Query(None),
    warehouse_id: Optional[int] = Query(None),
    kode_lambung_id: Optional[int] = Query(None),
    search_key: Optional[str] = Query(None),
    is_picker_view: Optional[bool] = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db),
    to_date : Optional[date] = Query(None, description="Filter by date"),
    from_date : Optional[date] = Query(None, description="Filter by date")

):
    query = (
        db.query(Penjualan)
        .options(
            selectinload(Penjualan.penjualan_items),
            selectinload(Penjualan.attachments),
            selectinload(Penjualan.customer_rel),
            selectinload(Penjualan.warehouse_rel),
            selectinload(Penjualan.kode_lambung_rel),  # NEW: Add kode_lambung loading
        )
        .filter(Penjualan.is_deleted == False)
        .order_by(
            cast(func.substr(Penjualan.no_penjualan,
                             func.length(Penjualan.no_penjualan) - 3), Integer).desc(),
            cast(func.substr(Penjualan.no_penjualan,
                             func.length(Penjualan.no_penjualan) - 6, 2), Integer).desc(),
            cast(func.substr(Penjualan.no_penjualan, 7, 4), Integer).desc()
        )
    )
    if is_picker_view is True:
        query = query.filter(Penjualan.status_pembayaran != StatusPembayaranEnum.PAID, Penjualan.status_penjualan != StatusPembelianEnum.DRAFT,  Penjualan.status_penjualan != StatusPembelianEnum.COMPLETED)

    if status_penjualan is not None and status_penjualan != StatusPembelianEnum.ALL:
        if status_penjualan in (StatusPembelianEnum.ACTIVE, StatusPembelianEnum.PROCESSED):
            query = query.filter(
                (Penjualan.status_penjualan == StatusPembelianEnum.ACTIVE)
                | (Penjualan.status_penjualan == StatusPembelianEnum.PROCESSED)
            )
        else:
            query = query.filter(Penjualan.status_penjualan == status_penjualan)

    if status_pembayaran is not None and status_pembayaran != StatusPembayaranEnum.ALL:
        query = query.filter(Penjualan.status_pembayaran == status_pembayaran)

    if search_key:
        query = query.filter(Penjualan.no_penjualan.ilike(f"%{search_key}%"))
    if customer_id:
        query = query.filter(Penjualan.customer_id == customer_id)
    if warehouse_id:
        query = query.filter(Penjualan.warehouse_id == warehouse_id)
    if kode_lambung_id:
        query = query.filter(Penjualan.kode_lambung_id == kode_lambung_id)

    if from_date and to_date:
            query = query.filter(
                Penjualan.sales_date.between(
                    datetime.combine(from_date, time.min),
                    datetime.combine(to_date, time.max),
                )
            )
    elif from_date:
        query = query.filter(Penjualan.sales_date >= datetime.combine(from_date, time.min))
    elif to_date:
        query = query.filter(Penjualan.sales_date <= datetime.combine(to_date, time.max))

    total = query.count()
    offset = (page - 1) * size
    rows = query.order_by(desc(Penjualan.sales_date)).offset(offset).limit(size).all()

    data = []
    for p in rows:
        customer_name = p.customer_name or (p.customer_rel.name if p.customer_rel else None)
        warehouse_name = p.warehouse_name or (p.warehouse_rel.name if p.warehouse_rel else None)
        kode_lambung_name = p.kode_lambung_rel.name if p.kode_lambung_rel else None

        data.append(
            PenjualanListResponse(
                id=p.id,
                no_penjualan=p.no_penjualan,
                status_pembayaran=p.status_pembayaran,
                status_penjualan=p.status_penjualan,
                sales_date=p.sales_date,
                total_paid=p.total_paid.quantize(Decimal("0.0001")),
                total_return=p.total_return.quantize(Decimal("0.0001")),
                total_price=p.total_price.quantize(Decimal("0.0001")),
                remaining=p.remaining.quantize(Decimal("0.0001")),
                items_count=len(p.penjualan_items),
                attachments_count=len(p.attachments),
                customer_name=customer_name,
                warehouse_name=warehouse_name,
                kode_lambung_name=kode_lambung_name,
            )
        )

    return {"data": data, "total": total}


@router.get("/{penjualan_id}", response_model=PenjualanResponse)
async def get_penjualan(penjualan_id: int, db: Session = Depends(get_db)):
    penjualan = (
        db.query(Penjualan)
        .options(
            selectinload(Penjualan.penjualan_items).selectinload(PenjualanItem.item_rel),
            selectinload(Penjualan.attachments),
            selectinload(Penjualan.customer_rel),
            selectinload(Penjualan.warehouse_rel),
            selectinload(Penjualan.top_rel),
            selectinload(Penjualan.kode_lambung_rel),  # NEW: Add kode_lambung loading
        )
        .filter(Penjualan.id == penjualan_id)
        .first()
    )
    if not penjualan:
        raise HTTPException(status_code=404, detail="Penjualan not found")
    return penjualan
@router.post("", status_code=status.HTTP_201_CREATED)
async def create_penjualan(request: PenjualanCreate, db: Session = Depends(get_db),user_name : str = Depends(get_current_user_name)):
    """
    Create new penjualan in DRAFT (no stock manipulation yet).
    We still validate stock availability per line so you don't draft impossible orders.
    """
    _validate_items_payload(request.items)
    for it in request.items:
        validate_item_stock(db, it.item_id, it.qty)



    p = Penjualan(
        no_penjualan=generate_unique_record_number(db, Penjualan, prefix="QP/SI"),
        warehouse_id=request.warehouse_id,
        customer_id=request.customer_id,
        top_id=request.top_id,
        kode_lambung_id=request.kode_lambung_id,
        sales_date=request.sales_date,
        sales_due_date=request.sales_due_date,
        additional_discount=request.additional_discount or Decimal("0"),
        expense=request.expense or Decimal("0"),
        status_penjualan=StatusPembelianEnum.DRAFT,
        currency_amount=request.currency_amount or Decimal("0"),
    )
    db.add(p)
    db.flush()

    for it in request.items:
        item = validate_item_exists(db, it.item_id)
        unit_price = Decimal(str(it.unit_price)) if it.unit_price is not None else Decimal(str(item.price))
        unit_price_rmb = (
            Decimal(str(it.unit_price_rmb)) if it.unit_price_rmb is not None else Decimal(str(item.price))
        )

        line = PenjualanItem(
            penjualan_id=p.id,
            item_id=item.id,
            qty=it.qty,
            unit_price=unit_price,
            unit_price_rmb=unit_price_rmb,
            tax_percentage=it.tax_percentage or 0,
            discount=it.discount or Decimal("0"),
        )
        calculate_item_totals(line)
        db.add(line)

    db.commit()
    calculate_penjualan_totals(db, p.id, "telah dibuat", user_name)

    return {"detail": "Penjualan created successfully", "id": p.id}

@router.put("/{penjualan_id}", response_model=PenjualanResponse)
async def update_penjualan(
        penjualan_id: int,
        request: PenjualanUpdate,
        db: Session = Depends(get_db),
        user_name: str = Depends(get_current_user_name)
):
    """
    Update penjualan:
    - If DRAFT: never touch inventory ledger
    - If ACTIVE/PROCESSED: void old ledger entries and post new ones for changed items
    """
    fields_changed = None

    penjualan: Penjualan = (
        db.query(Penjualan)
        .options(selectinload(Penjualan.penjualan_items))
        .filter(Penjualan.id == penjualan_id)
        .first()
    )
    if not penjualan:
        raise HTTPException(status_code=404, detail="Penjualan not found")

    # Enforce unique number if changed
    if request.no_penjualan and request.no_penjualan != penjualan.no_penjualan:
        exists = (
            db.query(Penjualan)
            .filter(and_(Penjualan.no_penjualan == request.no_penjualan, Penjualan.id != penjualan_id))
            .first()
        )
        if exists:
            raise HTTPException(status_code=400, detail="No penjualan already exists")

    # Handle kode_lambung_id changes (explicit re-link)
    if request.kode_lambung_id is not None and request.kode_lambung_id != penjualan.kode_lambung_id:
        target = db.query(KodeLambung).filter(KodeLambung.id == request.kode_lambung_id).first()
        if not target:
            raise HTTPException(status_code=404, detail="Kode Lambung not found")
        penjualan.kode_lambung_id = target.id
        fields_changed = True

    # Handle kode_lambung (string) with rename-semantics
    if request.kode_lambung is not None:
        new_name = request.kode_lambung.strip() or None

        current_kl = None
        if penjualan.kode_lambung_id:
            current_kl = db.query(KodeLambung).filter(KodeLambung.id == penjualan.kode_lambung_id).first()

        if current_kl is None:
            if new_name:
                existing = db.query(KodeLambung).filter(KodeLambung.name == new_name).first()
                if existing:
                    penjualan.kode_lambung_id = existing.id
                else:
                    created = KodeLambung(name=new_name)
                    db.add(created)
                    db.flush()
                    penjualan.kode_lambung_id = created.id
                fields_changed = True
            else:
                penjualan.kode_lambung_id = None
                fields_changed = True
        else:
            if not new_name:
                penjualan.kode_lambung_id = None
                fields_changed = True
            elif current_kl.name != new_name:
                usage_count = (
                    db.query(func.count(Penjualan.id))
                    .filter(Penjualan.kode_lambung_id == current_kl.id)
                    .scalar()
                )

                if usage_count <= 1:
                    conflict = (
                        db.query(KodeLambung)
                        .filter(and_(KodeLambung.name == new_name, KodeLambung.id != current_kl.id))
                        .first()
                    )
                    if conflict:
                        penjualan.kode_lambung_id = conflict.id
                    else:
                        current_kl.name = new_name
                else:
                    existing = db.query(KodeLambung).filter(KodeLambung.name == new_name).first()
                    if existing:
                        penjualan.kode_lambung_id = existing.id
                    else:
                        created = KodeLambung(name=new_name)
                        db.add(created)
                        db.flush()
                        penjualan.kode_lambung_id = created.id
                fields_changed = True

    # Handle other field updates
    update_data = request.dict(exclude_unset=True)
    items_data = update_data.pop("items", None)
    update_data.pop("discount", None)
    update_data.pop("kode_lambung", None)
    update_data.pop("kode_lambung_id", None)

    for field, value in update_data.items():
        if getattr(penjualan, field, None) != value:
            setattr(penjualan, field, value)
            fields_changed = True

    items_changed = False
    ledger_operations = []  # Track ledger changes: (operation, item_id, old_qty, new_qty, line_id)

    if items_data is not None:
        _validate_items_payload(items_data)
        current: dict[int, PenjualanItem] = {pi.item_id: pi for pi in penjualan.penjualan_items}
        incoming_ids = set()

        for raw in items_data:
            d = _normalize_item_payload(raw)
            item_id = int(d["item_id"])
            incoming_ids.add(item_id)
            item = validate_item_exists(db, item_id)

            if item_id in current:
                pi = current[item_id]
                old_qty = int(pi.qty or 0)
                new_qty = int(d["qty"])

                # Track changes for ledger updates
                if penjualan.status_penjualan in (StatusPembelianEnum.ACTIVE, StatusPembelianEnum.PROCESSED):
                    if old_qty != new_qty:
                        validate_item_stock(db, item_id, new_qty)
                        ledger_operations.append(("update", item_id, old_qty, new_qty, pi.id))

                if (
                        old_qty != new_qty
                        or Decimal(str(pi.unit_price or 0)) != d["unit_price"]
                        or int(pi.tax_percentage or 0) != d["tax_percentage"]
                        or Decimal(str(pi.discount or 0)) != d["discount"]
                ):
                    pi.qty = new_qty
                    pi.unit_price = d["unit_price"]
                    pi.tax_percentage = d["tax_percentage"]
                    pi.discount = d["discount"]
                    calculate_item_totals(pi)
                    items_changed = True
            else:
                # New item
                if penjualan.status_penjualan in (StatusPembelianEnum.ACTIVE, StatusPembelianEnum.PROCESSED):
                    validate_item_stock(db, item_id, d["qty"])

                nl = PenjualanItem(
                    penjualan_id=penjualan_id,
                    item_id=item.id,
                    qty=int(d["qty"]),
                    unit_price=d["unit_price"],
                    tax_percentage=int(d["tax_percentage"]),
                    discount=d["discount"],
                )
                calculate_item_totals(nl)
                db.add(nl)
                db.flush()  # Get the ID for ledger posting

                if penjualan.status_penjualan in (StatusPembelianEnum.ACTIVE, StatusPembelianEnum.PROCESSED):
                    ledger_operations.append(("add", item_id, 0, nl.qty, nl.id))

                items_changed = True

        # Handle deleted items
        for item_id, pi in list(current.items()):
            if item_id not in incoming_ids:
                if penjualan.status_penjualan in (StatusPembelianEnum.ACTIVE, StatusPembelianEnum.PROCESSED):
                    ledger_operations.append(("delete", item_id, pi.qty, 0, pi.id))
                db.delete(pi)
                items_changed = True

        # Apply ledger operations if not DRAFT
        if penjualan.status_penjualan in (StatusPembelianEnum.ACTIVE, StatusPembelianEnum.PROCESSED):
            trx_date = penjualan.sales_date.date() if isinstance(penjualan.sales_date, datetime) else penjualan.sales_date
            
            for operation, item_id, old_qty, new_qty, line_id in ledger_operations:
                if operation == "delete":
                    # Rollback the FIFO sale
                    try:
                        FifoService.rollback_sale(
                            db=db,
                            invoice_id=penjualan.no_penjualan,
                            invoice_date=trx_date
                        )
                        # Restore stock
                        update_item_stock(db, item_id, old_qty)
                    except ValueError as e:
                        raise HTTPException(
                            status_code=400,
                            detail=f"Cannot delete item - not the latest sale. Rollback newer sales first."
                        )

                elif operation == "update":
                    # Rollback old quantity
                    try:
                        FifoService.rollback_sale(
                            db=db,
                            invoice_id=penjualan.no_penjualan,
                            invoice_date=trx_date
                        )
                        # Restore old stock
                        update_item_stock(db, item_id, old_qty)
                    except ValueError as e:
                        raise HTTPException(
                            status_code=400,
                            detail=f"Cannot update item - not the latest sale. Rollback newer sales first."
                        )
                    
                    # Validate new quantity is available
                    validate_item_stock(db, item_id, new_qty, penjualan.warehouse_id)
                    
                    # Process new sale through FIFO
                    total_hpp, fifo_logs = FifoService.process_sale_fifo(
                        db=db,
                        invoice_id=penjualan.no_penjualan,
                        invoice_date=trx_date,
                        item_id=item_id,
                        qty_terjual=new_qty,
                        harga_jual_per_unit=Decimal(str(d["unit_price"])),
                        warehouse_id=penjualan.warehouse_id
                    )
                    # Reduce new stock
                    update_item_stock(db, item_id, -new_qty)

                elif operation == "add":
                    # Validate stock is available
                    validate_item_stock(db, item_id, new_qty, penjualan.warehouse_id)
                    
                    # Process new sale through FIFO
                    total_hpp, fifo_logs = FifoService.process_sale_fifo(
                        db=db,
                        invoice_id=penjualan.no_penjualan,
                        invoice_date=trx_date,
                        item_id=item_id,
                        qty_terjual=new_qty,
                        harga_jual_per_unit=Decimal(str(d["unit_price"])),
                        warehouse_id=penjualan.warehouse_id
                    )
                    # Reduce stock
                    update_item_stock(db, item_id, -new_qty)

    if fields_changed or items_changed:
        db.commit()
        calculate_penjualan_totals(db, penjualan_id, "telah diubah", user_name=user_name)
        db.commit()
    else:
        db.rollback()

    return await get_penjualan(penjualan_id, db)



@router.patch("/{penjualan_id}", status_code=status.HTTP_200_OK)
async def rollback_penjualan_status(
        penjualan_id: int,
        db: Session = Depends(get_db),
        user_name: str = Depends(get_current_user_name)
):
    """
    Roll back Penjualan to DRAFT from ACTIVE/COMPLETED.
    Creates reversal FIFO entries instead of deleting (maintains audit trail).
    """
    audit_service = AuditService(db)

    penjualan = (
        db.query(Penjualan)
        .options(selectinload(Penjualan.penjualan_items))
        .filter(Penjualan.id == penjualan_id)
        .first()
    )
    if not penjualan:
        raise HTTPException(status_code=404, detail="Penjualan not found")

    if penjualan.status_penjualan in (StatusPembelianEnum.ACTIVE, StatusPembelianEnum.COMPLETED):
        trx_date = penjualan.sales_date.date() if isinstance(penjualan.sales_date, datetime) else penjualan.sales_date
        
        try:
            # Rollback the FIFO sale - creates reversal entries
            result = FifoService.rollback_sale(
                db=db,
                invoice_id=penjualan.no_penjualan,
                rollback_date=trx_date
            )
            
            # Restore item stock for each line
            for line in penjualan.penjualan_items:
                update_item_stock(db, line.item_id, line.qty)
            
        except ValueError as e:
            # Insufficient qty error or already rolled back
            db.rollback()
            raise HTTPException(
                status_code=400,
                detail=str(e)  # This will show "INSUFFICIENT QTY, CANNOT ROLLBACK"
            )
        except Exception as e:
            db.rollback()
            raise HTTPException(
                status_code=500,
                detail=f"Error rolling back penjualan: {str(e)}"
            )

        # Clear status and snapshot fields
        penjualan.status_penjualan = StatusPembelianEnum.DRAFT
        penjualan.warehouse_name = None
        penjualan.customer_name = None
        penjualan.customer_address = None
        penjualan.top_name = None
        penjualan.currency_name = None

        audit_service.default_log(
            entity_id=penjualan.id,
            entity_type=AuditEntityEnum.PENJUALAN,
            description=f"Penjualan {penjualan.no_penjualan} rolled back: {result.get('reversal_id', 'N/A')}",
            user_name=user_name
        )

    db.commit()
    return {
        "msg": "Penjualan rolled back successfully", 
        "reversal_id": result.get('reversal_id'),
        "items_rolled_back": result.get('items_rolled_back')
    }

    
@router.post("/{penjualan_id}/finalize", response_model=PenjualanResponse)
async def finalize_penjualan_endpoint(penjualan_id: int, db: Session = Depends(get_db), user_name : str = Depends(get_current_user_name)):
    finalize_penjualan(db, penjualan_id, user_name)
    return await get_penjualan(penjualan_id, db)


@router.put("/{penjualan_id}/status", response_model=PenjualanResponse)
async def update_status(penjualan_id: int, request: PenjualanStatusUpdate, db: Session = Depends(get_db)):
    penjualan = db.query(Penjualan).filter(Penjualan.id == penjualan_id).first()
    if not penjualan:
        raise HTTPException(status_code=404, detail="Penjualan not found")

    if request.status_penjualan:
        penjualan.status_penjualan = request.status_penjualan
    if request.status_pembayaran:
        penjualan.status_pembayaran = request.status_pembayaran

    db.commit()
    return await get_penjualan(penjualan_id, db)



@router.post("/{penjualan_id}/upload-attachments", response_model=UploadResponse)
async def upload_attachments(
        penjualan_id: str,
        files: List[UploadFile] = File(...),
        db: Session = Depends(get_db)
):
    """Upload multiple attachment files for penjualan"""

    penjualan = db.query(Penjualan).filter(Penjualan.id == penjualan_id).first()
    if not penjualan:
        raise HTTPException(status_code=404, detail="penjualan not found")

    uploaded_files = []

    for file in files:
        # Validate file type
        if file.content_type not in ALLOWED_FILE_TYPES:
            raise HTTPException(
                status_code=400,
                detail=f"File type {file.content_type} not allowed. Only PDF, JPG, PNG files are allowed."
            )

        # Save file
        file_path = save_uploaded_file(file, penjualan_id)

        attachment = AllAttachment(
            parent_type=ParentType.PENJUALANS,
            penjualan_id=penjualan_id,
            filename=file.filename,
            file_path=file_path,
            file_size=file.size,
            mime_type=file.content_type
        )

        db.add(attachment)
        uploaded_files.append({
            "filename": file.filename,
            "size": file.size,
            "type": file.content_type
        })

    db.commit()

    return UploadResponse(
        message=f"Successfully uploaded {len(files)} files",
        files=uploaded_files
    )

@router.delete("/{penjualan_id}/attachments/{attachment_id}", response_model=SuccessResponse)
async def delete_attachment(
        penjualan_id: str,
        attachment_id: int,
        db: Session = Depends(get_db)
):
    """Delete specific attachment"""

    attachment = db.query(AllAttachment).filter(
        and_(
            AllAttachment.id == attachment_id,
            AllAttachment.penjualan_id == penjualan_id
        )
    ).first()

    if not attachment:
        raise HTTPException(status_code=404, detail="Attachment not found")

    if os.path.exists(attachment.file_path):
        os.remove(attachment.file_path)

    # Delete database record
    db.delete(attachment)
    db.commit()

    return SuccessResponse(message="Attachment deleted successfully")

@router.get("/{penjualan_id}/download/{attachment_id}")
async def download_attachment(
        penjualan_id: str,
        attachment_id: int,
        db: Session = Depends(get_db)
):
    """Download attachment file"""

    attachment = db.query(AllAttachment).filter(
        and_(
            AllAttachment.id == attachment_id,
            AllAttachment.penjualan_id == penjualan_id
        )
    ).first()

    if not attachment:
        raise HTTPException(status_code=404, detail="Attachment not found")

    if not os.path.exists(attachment.file_path):
        raise HTTPException(status_code=404, detail="File not found on server")

    return FileResponse(
        path=attachment.file_path,
        filename=attachment.filename,
        media_type=attachment.mime_type
    )

@router.get("/{penjualan_id}/totals", response_model=TotalsResponse)
async def get_totals(penjualan_id: int, db: Session = Depends(get_db)):
    data = calculate_penjualan_totals(db, penjualan_id)
    return TotalsResponse(**data)

@router.post("/{penjualan_id}/recalculate", response_model=TotalsResponse)
async def recalc_totals(penjualan_id: int, db: Session = Depends(get_db)):
    data = calculate_penjualan_totals(db, penjualan_id)
    return TotalsResponse(**data)

@router.delete("/{penjualan_id}", response_model=SuccessResponse)
async def delete_penjualan(penjualan_id: int, db: Session = Depends(get_db)):
    """
    Delete Penjualan:
      - If DRAFT and no payments -> HARD DELETE (doc + lines + files + kode_lambung).
      - Else -> SOFT DELETE (archive) + also soft-delete kode_lambung.
    """
    penjualan = (
        db.query(Penjualan)
        .options(
            selectinload(Penjualan.penjualan_items),
            selectinload(Penjualan.attachments),
            selectinload(Penjualan.pembayaran_detail_rel),
            selectinload(Penjualan.kode_lambung_rel),  
        )
        .filter(Penjualan.id == penjualan_id)
        .first()
    )
    if not penjualan:
        raise HTTPException(status_code=404, detail="Penjualan not found")

    validate_draft_status(penjualan)  # if you require DRAFT for hard delete

    has_payments = bool(penjualan.pembayaran_detail_rel)
    kode_lambung = penjualan.kode_lambung_rel  # may be None

    # --- Path A: HARD DELETE (DRAFT & no payments) ---
    if penjualan.status_penjualan.name == "DRAFT" and not has_payments:
        try:
            # delete files
            for att in penjualan.attachments:
                if att.file_path and os.path.exists(att.file_path):
                    try:
                        os.remove(att.file_path)
                    except Exception:
                        pass

            # delete child rows
            db.query(PenjualanItem).filter(
                PenjualanItem.penjualan_id == penjualan_id
            ).delete(synchronize_session=False)

            db.query(AllAttachment).filter(
                AllAttachment.penjualan_id == penjualan_id
            ).delete(synchronize_session=False)

            # IMPORTANT: detach FK, then delete kode_lambung (1-1 lifecycle)
            if kode_lambung:
                penjualan.kode_lambung_id = None
                db.flush()        # ensure FK cleared before deleting parent row
                db.delete(kode_lambung)

            # delete header
            db.delete(penjualan)
            db.commit()
            return SuccessResponse(message="Penjualan (DRAFT) deleted successfully")
        except Exception as e:
            db.rollback()
            raise HTTPException(status_code=500, detail=f"Error deleting penjualan: {str(e)}")

    # --- Path B: SOFT DELETE (not DRAFT or has payments) ---
    try:
        penjualan.is_deleted = True
        penjualan.deleted_at = datetime.utcnow()

        # Mirror soft-delete to kode_lambung so the 1-1 stays consistent
        if kode_lambung:
            kode_lambung.is_deleted = True
            kode_lambung.deleted_at = datetime.utcnow()

        db.commit()
        return SuccessResponse(
            message="Penjualan archived (soft deleted). Items, payments, and kode_lambung preserved (soft deleted)."
        )
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error archiving penjualan: {str(e)}")
        
@router.get("/{penjualan_id}/invoice/html", response_class=HTMLResponse)
async def view_penjualan_invoice_html(penjualan_id: int, request: Request, db: Session = Depends(get_db)):
    penjualan = (
        db.query(Penjualan)
        .options(
            joinedload(Penjualan.customer_rel),
            joinedload(Penjualan.kode_lambung_rel),
            joinedload(Penjualan.penjualan_items)
                .joinedload(PenjualanItem.item_rel)
                .joinedload(Item.attachments),
        )
        .filter(Penjualan.id == penjualan_id)
        .first()
    )
    if not penjualan:
        raise HTTPException(status_code=404, detail="Penjualan not found")

    BASE_URL = os.getenv("BASE_URL", "http://localhost:8000")
    totals_data = calculate_penjualan_totals(db, penjualan_id, "")

    def get_image_as_base64(raw_image_path):
        """Convert image to base64 so it embeds in downloaded HTML"""
        if not raw_image_path:
            return None
        
        try:
            cleaned_path = str(raw_image_path).strip()
            
            # Remove unwanted prefixes
            for prefix in ["root/backend/", "/root/backend/", "backend/", "/backend/", "static/items/", "/static/items/"]:
                if cleaned_path.startswith(prefix):
                    cleaned_path = cleaned_path[len(prefix):]
                    break
            
            upload_dir = os.getenv("UPLOAD_DIR", "uploads/items")
            
            # Try different paths
            possible_paths = [
                cleaned_path,
                f"static/items/{os.path.basename(cleaned_path)}",
                f"uploads/items/{os.path.basename(cleaned_path)}",
                os.path.join(upload_dir, os.path.basename(cleaned_path)),
            ]
            
            for path in possible_paths:
                if os.path.exists(path):
                    with open(path, "rb") as f:
                        img_data = base64.b64encode(f.read()).decode("ascii")
                        mime_type = "image/jpeg"
                        if path.lower().endswith('.png'):
                            mime_type = "image/png"
                        elif path.lower().endswith('.webp'):
                            mime_type = "image/webp"
                        return f"data:{mime_type};base64,{img_data}"
            
            print(f"⚠️ Image not found: {raw_image_path}, tried: {possible_paths}")
            return None
            
        except Exception as e:
            print(f"❌ Error loading image {raw_image_path}: {e}")
            return None

    enhanced_items = []
    
    for it in penjualan.penjualan_items:
        raw_image_path = it.primary_image_url if it.item_rel else None
        img_url = get_image_as_base64(raw_image_path)  # Use base64 instead of URL
        
        calculate_item_totals(it)
        
        qty = Decimal(str(it.qty or 0))
        unit_price = Decimal(str(it.unit_price or 0))
        tax_pct = Decimal(str(it.tax_percentage or 0))
        item_discount = Decimal(str(it.discount or 0))
        
        row_sub_total = qty * unit_price
        taxable_base = max(row_sub_total - item_discount, Decimal('0'))
        item_tax = (taxable_base * tax_pct) / Decimal('100')
        item_total_price = taxable_base + item_tax
        
        kode_lambung_name = penjualan.kode_lambung_rel.name if penjualan.kode_lambung_rel else None
        item_name = it.item_rel.name if it.item_rel else "Unknown Item"
        satuan_name = it.item_rel.satuan_rel.name if it.item_rel.satuan_rel else "Unknown Satuan"
        
        enhanced_items.append({
            "item": it,
            "image_url": img_url,  # Base64 data URL
            "item_name": item_name,
            "qty": it.qty,
            "satuan_name": satuan_name,
            "tax_percentage": it.tax_percentage,
            "unit_price": unit_price,
            "item_discount": item_discount,
            "item_subtotal_before_discount": row_sub_total,
            "item_subtotal_after_discount": taxable_base,
            "item_tax": item_tax,
            "total_price": item_total_price,
            "discount": item_discount,
        })

    additional_discount = Decimal(str(penjualan.additional_discount or 0))
    expense = Decimal(str(penjualan.expense or 0))

    totals = {
        "subtotal": totals_data["total_subtotal"],
        "item_discounts": totals_data["total_discount"],
        "additional_discount": additional_discount,
        "subtotal_after_discounts": totals_data["subtotal_after_item_discounts"],
        "final_total": totals_data["total_before_discount"],
        "tax_amount": totals_data["total_tax"],
        "expense": expense,
        "grand_total": totals_data["total_price"],
        "total_item_discount": totals_data["total_discount"],
    }

    # Load logo as base64
    import pathlib
    logo_data_url = None
    
    possible_logo_paths = [
        pathlib.Path("static/items/logo.png"),
        pathlib.Path("uploads/items/logo.png"),
        pathlib.Path("logo.png"),
    ]
    
    for logo_path in possible_logo_paths:
        if logo_path.exists():
            try:
                with logo_path.open("rb") as f:
                    logo_b64 = base64.b64encode(f.read()).decode("ascii")
                    logo_data_url = f"data:image/png;base64,{logo_b64}"
                break
            except Exception as e:
                print(f"Error reading logo from {logo_path}: {e}")
    
    if not logo_data_url:
        logo_data_url = ""

    return templates.TemplateResponse(
        "penjualan.html",
        {
            "request": request,
            "penjualan": penjualan,
            "enhanced_items": enhanced_items,
            "totals": totals,
            "kode_lambung_name": kode_lambung_name,
            "company": {
                "name": "PT. Jayagiri Indo Asia",
                "logo_url": logo_data_url,  # Base64 data URL
                "address": "Jl. Telkom No.188, Kota Bekasi, Jawa Barat 16340",
                "website": "www.qiuparts.com",
                "bank_name": "Bank Mandiri",
                "account_name": "PT. JAYAGIRI INDO ASIA",
                "account_number": "1670007971095",
                 "bank_name_bca": "Bank BCA",
                "account_name_bca": "PT. JAYAGIRI INDO ASIA",
                "account_number_bca": "7285834627",
                "representative": "",
            },
            "css": open("templates/invoice.css").read(),
        },
    )