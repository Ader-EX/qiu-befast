import random

from fastapi import APIRouter, Depends, HTTPException, File, UploadFile, Query, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session, selectinload, joinedload
from sqlalchemy import and_, func, desc
from typing import List, Optional
import uuid
import os
import shutil
import enum
from datetime import datetime
from decimal import Decimal, InvalidOperation

from starlette.requests import Request
from starlette.responses import HTMLResponse

from database import get_db
from models.Customer import Customer
from models.Pembayaran import  Pembayaran
from models.Penjualan import StatusPembayaranEnum, StatusPembelianEnum
from models.Penjualan import Penjualan, PenjualanItem

from models.Item import Item

from models.AllAttachment import ParentType, AllAttachment
from routes.upload_routes import get_public_image_url, to_public_image_url, templates
from schemas.PaginatedResponseSchemas import PaginatedResponse
from schemas.PenjualanSchema import PenjualanCreate, PenjualanListResponse, PenjualanResponse, PenjualanStatusUpdate, PenjualanUpdate, SuccessResponse, TotalsResponse, UploadResponse
from utils import generate_unique_record_number
from decimal import Decimal, InvalidOperation  # add InvalidOperation

router = APIRouter()

# Configuration
UPLOAD_DIR = os.getenv("STATIC_URL")
os.makedirs(UPLOAD_DIR, exist_ok=True)
ALLOWED_FILE_TYPES = ["application/pdf", "image/jpeg", "image/png", "image/jpg"]
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB

def calculate_item_totals(item: PenjualanItem) -> None:
    """
    Line totals:
      base = qty * unit_price
      taxable_base = base - discount
      line_tax = taxable_base * (tax% / 100)
      total_price = taxable_base + line_tax
    'price_after_tax' is stored for compatibility as a unit-equivalent:
      price_after_tax = total_price / qty (if qty > 0), else 0
    """
    qty = Decimal(str(item.qty or 0))
    unit_price = Decimal(str(item.unit_price or 0))
    tax_percentage = Decimal(str(item.tax_percentage or 0))
    discount = Decimal(str(item.discount or 0))

    base = qty * unit_price
    taxable_base = base - discount
    if taxable_base < 0:
        taxable_base = Decimal('0')  # safety clamp

    line_tax = (taxable_base * tax_percentage) / Decimal('100')
    total_price = taxable_base + line_tax

    item.sub_total = base  # before any discount/tax (matches your UI "Sub Total")
    item.total_price = total_price

    # For compatibility. If you truly need "unit price after tax", this is a
    # derived average when discount exists.
    item.price_after_tax = (total_price / qty) if qty else Decimal('0')


def validate_item_exists(db: Session, item_id: int) -> Item:
    item = db.query(Item).filter(Item.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail=f"Item with ID {item_id} not found")
    return item


def validate_item_stock(db: Session, item_id: int, requested_qty: int) -> None:
    """Ensure stock is sufficient for a SALES operation (will subtract on finalize)."""
    item = validate_item_exists(db, item_id)
    available = int(item.total_item or 0)
    if requested_qty < 1:
        raise HTTPException(status_code=400, detail="qty must be >= 1")
    if available < requested_qty:
        raise HTTPException(
            status_code=400,
            detail=f"Stock untuk item '{item.name}' tidak tersedia. "
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

def calculate_penjualan_totals(db: Session, penjualan_id: int):
    items = db.query(PenjualanItem).filter(PenjualanItem.penjualan_id == penjualan_id).all()

    total_subtotal = Decimal('0')
    total_discount = Decimal('0')
    total_tax = Decimal('0')
    total_grand_total_items = Decimal('0')  # Sum of individual item grand totals

    for line in items:
        # Recompute per the same rules as frontend
        calculate_item_totals(line)

        qty = Decimal(str(line.qty or 0))
        unit = Decimal(str(line.unit_price or 0))
        tax_pct = Decimal(str(line.tax_percentage or 0))
        discount = Decimal(str(line.discount or 0))

        # Frontend logic: tax calculated on full amount, then discount applied
        base = qty * unit  # subtotal (unit * qty)
        unit_with_tax = unit * (Decimal('1') + tax_pct / Decimal('100'))  # unit price including tax
        total_with_tax = unit_with_tax * qty  # total including tax
        item_tax = total_with_tax - base  # tax amount for this line
        item_grand_total = max(total_with_tax - discount, Decimal('0'))  # grand total after discount

        total_subtotal += base
        total_discount += discount
        total_tax += item_tax
        total_grand_total_items += item_grand_total

    penjualan = db.query(Penjualan).filter(Penjualan.id == penjualan_id).first()
    if not penjualan:
        raise HTTPException(status_code=404, detail="Penjualan not found")

    additional_discount = Decimal(str(penjualan.additional_discount or 0))
    expense = Decimal(str(penjualan.expense or 0))

    # Calculate totals to match frontend
    subtotal_after_item_discounts = total_subtotal - total_discount
    final_total_before_tax = max(subtotal_after_item_discounts - additional_discount, Decimal('0'))
    
    # Grand total should match the sum of individual item grand totals + additional discount effect + expense
    # But according to your frontend logic, it's: finalTotalBeforeTax + totalTax + expense
    total_price = final_total_before_tax + total_tax + expense

    penjualan.total_subtotal = total_subtotal
    penjualan.total_discount = total_discount
    penjualan.additional_discount = additional_discount
    penjualan.total_before_discount = final_total_before_tax 
    penjualan.total_tax = total_tax
    penjualan.expense = expense
    penjualan.total_price = total_price
    penjualan.total_qty = sum(int(it.qty or 0) for it in items)

    db.commit()

    return {
        "total_subtotal": total_subtotal,
        "total_discount": total_discount,
        "additional_discount": additional_discount,
        "total_before_discount": final_total_before_tax,
        "total_tax": total_tax,
        "expense": expense,
        "total_price": total_price,
        "total_qty": penjualan.total_qty,
        "total_grand_total_items": total_grand_total_items,  # For debugging
    }


def finalize_penjualan(db: Session, penjualan_id: int):
    """
    Finalize SALES:
      - Validate required fields
      - Validate stock availability per line
      - Subtract qty from stock for each line
      - Snapshot friendly names
      - Set status ACTIVE
    """
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

    # 1) Validate stock first (checker)
    for line in penjualan.penjualan_items:
        validate_item_stock(db, line.item_id, line.qty)

    # 2) Snapshot names / metadata (like your Pembelian)
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

    # 3) Subtract stock per line
    for line in penjualan.penjualan_items:
        # Keep some item snapshots if needed (optional)
        if line.item_rel:
            item = line.item_rel
            if getattr(item, "satuan_rel", None):
                line.satuan_name = item.satuan_rel.name
        update_item_stock(db, line.item_id, -int(line.qty or 0))  # sales → subtract

    # 4) Activate
    penjualan.status_penjualan = StatusPembelianEnum.ACTIVE
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
    search_key: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db),
):
    query = (
        db.query(Penjualan)
        .options(
            selectinload(Penjualan.penjualan_items),
            selectinload(Penjualan.attachments),
            selectinload(Penjualan.customer_rel),
            selectinload(Penjualan.warehouse_rel),
        )
        .filter(Penjualan.is_deleted == False)
    )

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

    total = query.count()
    offset = (page - 1) * size
    rows = query.order_by(desc(Penjualan.sales_date)).offset(offset).limit(size).all()

    data = []
    for p in rows:
        customer_name = p.customer_name or (p.customer_rel.name if p.customer_rel else None)
        warehouse_name = p.warehouse_name or (p.warehouse_rel.name if p.warehouse_rel else None)

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
        )
        .filter(Penjualan.id == penjualan_id)
        .first()
    )
    if not penjualan:
        raise HTTPException(status_code=404, detail="Penjualan not found")
    return penjualan


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_penjualan(request: PenjualanCreate, db: Session = Depends(get_db)):
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
        sales_date=request.sales_date,
        sales_due_date=request.sales_due_date,
        additional_discount=request.additional_discount or Decimal("0"),
        expense=request.expense or Decimal("0"),
        status_penjualan=StatusPembelianEnum.DRAFT,
    )
    db.add(p)
    db.flush()

    for it in request.items:
        item = validate_item_exists(db, it.item_id)
        unit_price = Decimal(str(it.unit_price)) if it.unit_price is not None else Decimal(str(item.price))
        line = PenjualanItem(
            penjualan_id=p.id,
            item_id=item.id,
            qty=it.qty,
            unit_price=unit_price,
            tax_percentage=it.tax_percentage or 0,
            discount=it.discount or Decimal("0"),
        )
        calculate_item_totals(line)
        db.add(line)

    db.commit()
    calculate_penjualan_totals(db, p.id)

    return {"detail": "Penjualan created successfully", "id": p.id}


@router.put("/{penjualan_id}", response_model=PenjualanResponse)
async def update_penjualan(penjualan_id: int, request: PenjualanUpdate, db: Session = Depends(get_db)):
    """
    Update penjualan.
    - If DRAFT: never touch stock.
    - If ACTIVE/PROCESSED: apply **delta** to stock (sales direction).
    """
    penjualan: Penjualan = (
        db.query(Penjualan)
        .options(selectinload(Penjualan.penjualan_items))
        .filter(Penjualan.id == penjualan_id)
        .first()
    )
    if not penjualan:
        raise HTTPException(status_code=404, detail="Penjualan not found")

    # enforce unique number if changed
    if request.no_penjualan and request.no_penjualan != penjualan.no_penjualan:
        exists = (
            db.query(Penjualan)
            .filter(and_(Penjualan.no_penjualan == request.no_penjualan, Penjualan.id != penjualan_id))
            .first()
        )
        if exists:
            raise HTTPException(status_code=400, detail="No penjualan already exists")

    update_data = request.dict(exclude_unset=True)
    items_data = update_data.pop("items", None)
    # guard against stray header 'discount' fields that don't exist
    update_data.pop("discount", None)

    fields_changed = False
    for field, value in update_data.items():
        if getattr(penjualan, field, None) != value:
            setattr(penjualan, field, value)
            fields_changed = True

    items_changed = False
    stock_adjustments: list[tuple[int, int]] = []

    if items_data is not None:
        _validate_items_payload(items_data)

        # Map existing
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

                # If finalized, compute delta for stock:
                if penjualan.status_penjualan in (StatusPembelianEnum.ACTIVE, StatusPembelianEnum.PROCESSED):
                    # sales: increase qty → subtract more; decrease qty → add back
                    delta = -(new_qty - old_qty)
                    if delta != 0:
                        # Check we won’t go below zero when subtracting
                        if delta < 0:
                            validate_item_stock(db, item_id, abs(delta))
                        stock_adjustments.append((item_id, delta))

                # Update line if changed
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
                # New line
                if penjualan.status_penjualan in (StatusPembelianEnum.ACTIVE, StatusPembelianEnum.PROCESSED):
                    # New sales line → subtract full qty
                    validate_item_stock(db, item_id, d["qty"])
                    stock_adjustments.append((item_id, -int(d["qty"])))

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
                items_changed = True

        # Deletions
        for item_id, pi in list(current.items()):
            if item_id not in incoming_ids:
                if penjualan.status_penjualan in (StatusPembelianEnum.ACTIVE, StatusPembelianEnum.PROCESSED):
                    # Removing a sales line → return that qty to stock
                    stock_adjustments.append((item_id, int(pi.qty or 0)))
                db.delete(pi)
                items_changed = True

        # Apply stock deltas if finalized
        if penjualan.status_penjualan in (StatusPembelianEnum.ACTIVE, StatusPembelianEnum.PROCESSED):
            for item_id, qty_change in stock_adjustments:
                if qty_change != 0:
                    update_item_stock(db, item_id, qty_change)

    if fields_changed or items_changed:
        db.commit()
        calculate_penjualan_totals(db, penjualan_id)
        db.commit()
    else:
        db.rollback()

    return await get_penjualan(penjualan_id, db)


@router.patch("/{penjualan_id}", status_code=status.HTTP_200_OK)
async def rollback_penjualan_status(penjualan_id: int, db: Session = Depends(get_db)):
    """
    Roll back Penjualan to DRAFT from ACTIVE/COMPLETED and reverse stock subtraction.
    """
    penjualan = (
        db.query(Penjualan)
        .options(selectinload(Penjualan.penjualan_items))
        .filter(Penjualan.id == penjualan_id)
        .first()
    )
    if not penjualan:
        raise HTTPException(status_code=404, detail="Penjualan not found")

    if penjualan.status_penjualan in (StatusPembelianEnum.ACTIVE, StatusPembelianEnum.COMPLETED):
        # Reverse: add back each qty
        for line in penjualan.penjualan_items:
            update_item_stock(db, line.item_id, int(line.qty or 0))

        penjualan.status_penjualan = StatusPembelianEnum.DRAFT
        penjualan.warehouse_name = None
        penjualan.customer_name = None
        penjualan.customer_address = None
        penjualan.top_name = None
        penjualan.currency_name = None

    db.commit()
    return {"msg": "Penjualan status changed successfully"}


@router.post("/{penjualan_id}/finalize", response_model=PenjualanResponse)
async def finalize_penjualan_endpoint(penjualan_id: int, db: Session = Depends(get_db)):
    finalize_penjualan(db, penjualan_id)
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
async def delete_penjualan(penjualan_id: str, db: Session = Depends(get_db)):
    """
    Delete Penjualan:
      - If DRAFT and no payments -> HARD DELETE (doc + lines + files).
      - Else (has payments or not DRAFT) -> SOFT DELETE (archive).
    """

    penjualan = (
        db.query(Penjualan)
        .options(
            selectinload(Penjualan.penjualan_items),
            selectinload(Penjualan.attachments),
            selectinload(Penjualan.pembayaran_detail_rel),   # load payments to decide path
        )
        .filter(Penjualan.id == penjualan_id)
        .first()
    )

    if not penjualan:
        raise HTTPException(status_code=404, detail="Penjualan not found")

    # If you already enforce DRAFT-only deletion, keep this. Otherwise, remove and rely on the branching below.
    # This will raise if not DRAFT.
    validate_draft_status(penjualan)

    has_payments = bool(penjualan.pembayaran_detail_rel)

    # --- Path A: HARD DELETE only if DRAFT and no payments ---
    if penjualan.status_penjualan.name == "DRAFT" and not has_payments:
        try:
            for att in penjualan.attachments:
                if att.file_path and os.path.exists(att.file_path):
                    try:
                        os.remove(att.file_path)
                    except Exception:
                        pass

            # 2) Delete child rows (or rely on cascade="all, delete-orphan")
            db.query(PenjualanItem).filter(
                PenjualanItem.penjualan_id == penjualan_id
            ).delete(synchronize_session=False)

            db.query(AllAttachment).filter(
                AllAttachment.penjualan_id == penjualan_id
            ).delete(synchronize_session=False)

            # IMPORTANT: Do NOT delete Pembayaran (shouldn't exist in this branch anyway)
            # db.query(Pembayaran).filter(Pembayaran.penjualan_id == penjualan_id).delete()

            # 3) Delete header
            db.delete(penjualan)
            db.commit()

            return SuccessResponse(message="Penjualan (DRAFT) deleted successfully")
        except Exception as e:
            db.rollback()
            raise HTTPException(
                status_code=500,
                detail=f"Error deleting penjualan: {str(e)}"
            )

    # --- Path B: SOFT DELETE (archive) if payments exist or not DRAFT ---
    try:
        penjualan.is_deleted = True
        penjualan.deleted_at = datetime.utcnow()
        db.commit()
        return SuccessResponse(
            message="Penjualan archived (soft deleted). Items and payments preserved."
        )
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Error archiving penjualan: {str(e)}"
        )


@router.get("/{penjualan_id}/invoice/html", response_class=HTMLResponse)
async def view_penjualan_invoice_html(penjualan_id: int, request: Request, db: Session = Depends(get_db)):
    penjualan = (
        db.query(Penjualan)
        .options(
            joinedload(Penjualan.customer_rel),
            joinedload(Penjualan.penjualan_items)
            .joinedload(PenjualanItem.item_rel)
            .joinedload(Item.attachments)
        )
        .filter(Penjualan.id == penjualan_id)
        .first()
    )
    if not penjualan:
        raise HTTPException(status_code=404, detail="Penjualan not found")

    BASE_URL = os.getenv("BASE_URL", "http://localhost:8000")

    enhanced_items = []
    subtotal_before_discount = Decimal('0')  # Subtotal before any discounts
    total_item_discounts = Decimal('0')      # Sum of all item discounts
    tax_amount = Decimal('0')
    
    for it in penjualan.penjualan_items:
        # FIXED: Use primary_image_url which returns raw path, not full URL
        raw_image_path = it.primary_image_url if it.item_rel else None
        img_url = get_public_image_url(raw_image_path, BASE_URL) if raw_image_path else None
        
        # Calculate item totals
        qty = Decimal(str(it.qty or 0))
        unit_price = Decimal(str(it.unit_price or 0))
        tax_pct = Decimal(str(it.tax_percentage or 0))
        item_discount = Decimal(str(it.discount or 0))  # This is the per-item discount
        
        # Calculate item subtotal before discount and tax
        item_subtotal_before_discount = qty * unit_price
        
        # Calculate item tax (applied after discount)
        item_subtotal_after_discount = item_subtotal_before_discount - item_discount
        item_tax = item_subtotal_after_discount * (tax_pct / Decimal(100))
        
        # Total price for this item (after discount + tax)
        item_total_price = item_subtotal_after_discount + item_tax
        
        enhanced_items.append({
            "item": it,
            "image_url": img_url,
            "item_name": it.item_name,
            "qty": it.qty,
            "satuan_name": it.satuan_name,
            "tax_percentage": it.tax_percentage,
            "unit_price": unit_price,
            "item_discount": item_discount,
            "item_subtotal_before_discount": item_subtotal_before_discount,
            "item_subtotal_after_discount": item_subtotal_after_discount,
            "item_tax": item_tax,
            "total_price": item_total_price,
            "discount": item_discount,  # Keep for backward compatibility
        })
        
        # Accumulate totals
        subtotal_before_discount += item_subtotal_before_discount
        total_item_discounts += item_discount
        tax_amount += item_tax

    # Calculate additional discount and final totals
    additional_discount = Decimal(str(penjualan.additional_discount or 0))
    expense = Decimal(str(penjualan.expense or 0))
    
    # Calculate subtotal after item discounts but before additional discount
    subtotal_after_item_discounts = subtotal_before_discount - total_item_discounts
    
    # Calculate final total before tax (after all discounts)
    final_total_before_tax = subtotal_after_item_discounts - additional_discount
    
    # Grand total (final total + tax + expense)
    grand_total = final_total_before_tax + tax_amount + expense

    # Match the template expectations
    totals = {
        "subtotal": subtotal_before_discount,           # Raw subtotal before any discounts
        "item_discounts": total_item_discounts,         # Sum of all per-item discounts  
        "additional_discount": additional_discount,     # Additional discount from penjualan
        "subtotal_after_discounts": subtotal_after_item_discounts,  # After item discounts
        "final_total": final_total_before_tax,          # After all discounts, before tax
        "tax_amount": tax_amount,
        "expense": expense,
        "grand_total": grand_total,
        # Keep backward compatibility
        "total_item_discount": total_item_discounts,  # Your original key
    }

    return templates.TemplateResponse(
        "penjualan.html",
        {
            "request": request,
            "penjualan": penjualan,
            "enhanced_items": enhanced_items,
            "totals": totals,
            "company": {
                "name": "PT. Jayagiri Indo Asia",
                "logo_url": get_public_image_url("logo.png", BASE_URL),  # FIXED: Use helper function
                "address": "Jl. Telkom No.188, Kota Bekasi, Jawa Barat 16340",
                "website": "www.qiupart.com",
                "bank_name": "Bank Mandiri",
                "account_name": "PT. JAYAGIRI INDO ASIA",
                "account_number": "167-00-07971095",
                "representative": "AMAR",
            },
            "css": open("templates/invoice.css").read(),
        },
    )