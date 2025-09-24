import mimetypes
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
from datetime import datetime, date, time
from decimal import Decimal

from starlette.responses import HTMLResponse

from database import get_db
from starlette.requests import Request

from models.AuditTrail import AuditEntityEnum
from models.Vendor import Vendor  
from models.Item import Item
from models.Pembelian import Pembelian, StatusPembelianEnum,PembelianItem, StatusPembayaranEnum
from models.AllAttachment import ParentType, AllAttachment
from routes.upload_routes import get_public_image_url, to_public_image_url, templates
from schemas.PaginatedResponseSchemas import PaginatedResponse
from schemas.PembelianSchema import TotalsResponse, PembelianListResponse, PembelianResponse, PembelianCreate, \
    PembelianUpdate, PembelianStatusUpdate, UploadResponse, SuccessResponse
from services.audit_services import AuditService
from utils import generate_unique_record_number, get_current_user_name

router = APIRouter()

# Configuration
UPLOAD_DIR = os.getenv("STATIC_URL")
os.makedirs(UPLOAD_DIR, exist_ok=True)
ALLOWED_FILE_TYPES = ["application/pdf", "image/jpeg", "image/png", "image/jpg"]
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB


def calculate_item_totals(item: PembelianItem) -> None:
    """
    Line totals (pembelian):
      base = qty * unit_price
      taxable_base = base - discount
      line_tax = taxable_base * (tax% / 100)
      total_price = taxable_base + line_tax

    Stored fields:
      - sub_total = base (pre-discount, pre-tax)  ← matches your UI "Sub Total"
      - total_price = final line total (after discount + tax)
      - price_after_tax = total_price / qty  (average unit price incl. tax & any line discount)
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

    item.sub_total = base
    item.total_price = total_price
    item.price_after_tax = (total_price / qty) if qty else Decimal('0')

def validate_item_exists(db: Session, item_id: int) -> Item:
    """Validate if item exists and return it"""
    item = db.query(Item).filter(Item.id == item_id).first()
    if not item:
        raise HTTPException(
            status_code=404,
            detail=f"Item with ID {item_id} not found"
        )
    return item

def update_item_stock(db: Session, item_id: int, qty_change: int) -> None:
    """Update item stock by the specified quantity change (can be positive or negative)"""
    item = validate_item_exists(db, item_id)
    
    # Initialize total_item if it's None
    if item.total_item is None:
        item.total_item = 0
    
    # Apply the quantity change (for purchases, this should be positive to add stock)
    item.total_item = item.total_item + qty_change

def calculate_pembelian_totals(db: Session, pembelian_id: int, user_name :str, msg : str ):

    audit_service = AuditService(db)
    items = db.query(PembelianItem).filter(PembelianItem.pembelian_id == pembelian_id).all()

    total_subtotal = Decimal('0')
    total_discount = Decimal('0')
    total_tax = Decimal('0')

    for line in items:
        calculate_item_totals(line)

        qty = Decimal(str(line.qty or 0))
        unit = Decimal(str(line.unit_price or 0))
        tax_pct = Decimal(str(line.tax_percentage or 0))
        discount = Decimal(str(line.discount or 0))

        base = qty * unit
        taxable_base = base - discount
        if taxable_base < 0:
            taxable_base = Decimal('0')

        line_tax = (taxable_base * tax_pct) / Decimal('100')

        total_subtotal += base
        total_discount += discount
        total_tax += line_tax

    pembelian = db.query(Pembelian).filter(Pembelian.id == pembelian_id).first()
    if not pembelian:
        raise HTTPException(status_code=404, detail="Pembelian not found")

    additional_discount = Decimal(str(pembelian.additional_discount or 0))
    expense = Decimal(str(pembelian.expense or 0))

    subtotal_after_item_discounts = total_subtotal - total_discount
    final_total_before_tax = subtotal_after_item_discounts - additional_discount
    total_price = final_total_before_tax + total_tax + expense

    # Persist
    pembelian.total_subtotal = total_subtotal
    pembelian.total_discount = total_discount
    pembelian.additional_discount = additional_discount
    pembelian.total_before_discount = final_total_before_tax  
    pembelian.total_tax = total_tax
    pembelian.expense = expense
    pembelian.total_price = total_price

    audit_service.default_log(
        entity_id=pembelian.id,
        entity_type=AuditEntityEnum.PEMBELIAN,
        description=f"Pembelian {pembelian.no_pembelian} {msg} : Total {pembelian.total_price} ",
        user_name=user_name
    )

    db.commit()

    return {
        "total_subtotal": total_subtotal,
        "total_discount": total_discount,
        "additional_discount": additional_discount,
        "total_before_discount": final_total_before_tax,
        "total_tax": total_tax,
        "expense": expense,
        "total_price": total_price,
    }

def finalize_pembelian(db: Session, pembelian_id: int, user_name : str):
    audit_service  = AuditService(db)
    """Finalize pembelian and update stock"""
    pembelian = db.query(Pembelian).options(
        selectinload(Pembelian.warehouse_rel),
        selectinload(Pembelian.vend_rel),
        selectinload(Pembelian.sumberdana_rel),
        selectinload(Pembelian.top_rel),
        selectinload(Pembelian.pembelian_items).selectinload(PembelianItem.item_rel)
    ).filter(Pembelian.id == pembelian_id).first()

    if not pembelian:
        raise HTTPException(status_code=404, detail="Pembelian not found")

    if pembelian.status_pembelian != StatusPembelianEnum.DRAFT:
        raise HTTPException(status_code=400, detail="Can only finalize DRAFT pembelians")

    # Validate required fields
    if not pembelian.warehouse_id or not pembelian.vendor_id or not pembelian.sumberdana_id:
        raise HTTPException(status_code=400, detail="Warehouse and Vendor are required for finalization")

    if not pembelian.pembelian_items:
        raise HTTPException(status_code=400, detail="At least one item is required for finalization")

    for pembelian_item in pembelian.pembelian_items:
        if pembelian_item.item_rel:
            item = pembelian_item.item_rel
            if hasattr(item, 'satuan_rel') and item.satuan_rel:
                pembelian_item.satuan_name = item.satuan_rel.name

        update_item_stock(db, pembelian_item.item_id, pembelian_item.qty)

    # Update status
    pembelian.status_pembelian = StatusPembelianEnum.ACTIVE

    audit_service.default_log(
        entity_id=pembelian.id,
        entity_type=AuditEntityEnum.PEMBELIAN,
        description=f"Pembelian {pembelian.no_pembelian} status transaksi diubah: Draft → Aktif",
        user_name=user_name
    )
    db.commit()

def validate_draft_status(pembelian: Pembelian):
    """Validate that pembelian is in DRAFT status for editing"""
    if pembelian.status_pembelian != StatusPembelianEnum.DRAFT:
        raise HTTPException(
            status_code=400,
            detail="Can only modify DRAFT pembelians"
        )

def save_uploaded_file(file: UploadFile, pembelian_id: int) -> str:
    """Save uploaded file and return file path"""
    if file.size > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"File size too large. Maximum size is {MAX_FILE_SIZE // (1024*1024)}MB"
        )

    file_extension = os.path.splitext(file.filename)[1]
    unique_filename = f"{pembelian_id}_{uuid.uuid4().hex[:8]}{file_extension}"
    file_path = os.path.join(UPLOAD_DIR, unique_filename)

    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    return file_path

# Validation helper functions
from decimal import Decimal, InvalidOperation

def _get_item_id(obj):
    return getattr(obj, "item_id", None) if not isinstance(obj, dict) else obj.get("item_id")

def _normalize_item_payload(obj):
    if isinstance(obj, dict):
        data = obj
    else:
        data = obj.dict() if hasattr(obj, "dict") else obj.model_dump()

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
                detail=f"items[{idx}]: discount must be between 0 and qty*unit_price (<= {max_discount})"
            )

# API Endpoints

@router.get("", response_model=PaginatedResponse[PembelianListResponse])
async def get_all_pembelian(
        status_pembelian: Optional[StatusPembelianEnum] = Query(None),
        status_pembayaran: Optional[StatusPembayaranEnum] = Query(None),
        vendor_id: Optional[str] = Query(None),
        search_key: Optional[str] = Query(None),
        warehouse_id: Optional[int] = Query(None),
        page: int = Query(1, ge=1),
        size: int = Query(50, ge=1, le=100),
        db: Session = Depends(get_db),
        to_date : Optional[date] = Query(None, description="Filter by date"),
        from_date : Optional[date] = Query(None, description="Filter by date"),
):
    """Get all pembelian with filtering and pagination"""

    query = db.query(Pembelian).options(
        selectinload(Pembelian.pembelian_items),
        selectinload(Pembelian.attachments),
        selectinload(Pembelian.vend_rel),
        selectinload(Pembelian.sumberdana_rel),
        selectinload(Pembelian.warehouse_rel)
    ).filter(Pembelian.is_deleted == False).order_by(
        cast(func.substr(Pembelian.no_pembelian,
                         func.length(Pembelian.no_pembelian) - 3), Integer).desc(),
        cast(func.substr(Pembelian.no_pembelian,
                         func.length(Pembelian.no_pembelian) - 6, 2), Integer).desc(),
        cast(func.substr(Pembelian.no_pembelian, 7, 4), Integer).desc()
    )

    # Apply filters
    if status_pembelian is not None and status_pembelian != StatusPembelianEnum.ALL:
        if status_pembelian == StatusPembelianEnum.ACTIVE or status_pembelian == StatusPembelianEnum.PROCESSED:
            query = query.filter(
                (Pembelian.status_pembelian == StatusPembelianEnum.ACTIVE) |
                (Pembelian.status_pembelian == StatusPembelianEnum.PROCESSED)
            )
        else:
            query = query.filter(Pembelian.status_pembelian == status_pembelian)
    
    if search_key:
        query = query.filter(Pembelian.no_pembelian.ilike(f"%{search_key}%"))

    if status_pembayaran is not None and status_pembayaran != StatusPembayaranEnum.ALL:
        query = query.filter(Pembelian.status_pembayaran == status_pembayaran)
    if vendor_id:
        query = query.filter(Pembelian.vendor_id == vendor_id)
    if warehouse_id:
        query = query.filter(Pembelian.warehouse_id == warehouse_id)


    if from_date and to_date:
        query = query.filter(
            Pembelian.sales_date.between(
                datetime.combine(from_date, time.min),
                datetime.combine(to_date, time.max),
            )
        )
    elif from_date:
        query = query.filter(Pembelian.sales_date >= datetime.combine(from_date, time.min))
    elif to_date:
        query = query.filter(Pembelian.sales_date <= datetime.combine(to_date, time.max))

    # Get total count before pagination
    total = query.count()
    
    # Apply pagination
    offset = (page - 1) * size
    pembelians = query.order_by(desc(Pembelian.sales_date)).offset(offset).limit(size).all()

    result = []
    for pembelian in pembelians:

        pembelian_dict = {
            "id": pembelian.id,
            "no_pembelian": pembelian.no_pembelian,
            "status_pembayaran": pembelian.status_pembayaran,
            "status_pembelian": pembelian.status_pembelian,
            "vendor_name"  : pembelian.vend_rel.name,
            "sales_date": pembelian.sales_date,
            "total_paid": pembelian.total_paid.quantize(Decimal('0.0001')),
            "total_return": pembelian.total_return.quantize(Decimal('0.0001')),
            "total_price": pembelian.total_price.quantize(Decimal('0.0001')),
            "remaining": pembelian.remaining.quantize(Decimal('0.0001')),  
            "items_count": len(pembelian.pembelian_items),
            "attachments_count": len(pembelian.attachments)
        }
        result.append(PembelianListResponse(**pembelian_dict))

    return {
        "data": result,
        "total": total,
    }

@router.get("/{pembelian_id}", response_model=PembelianResponse)
async def get_pembelian(pembelian_id: int, db: Session = Depends(get_db)): 
    pembelian = (
        db.query(Pembelian)
          .options(
              selectinload(Pembelian.pembelian_items)
                  .selectinload(PembelianItem.item_rel),
              selectinload(Pembelian.attachments),
              selectinload(Pembelian.vend_rel),
              selectinload(Pembelian.warehouse_rel),
              selectinload(Pembelian.top_rel),
          )
          .filter(Pembelian.id == pembelian_id)
          .first()
    )

    if not pembelian:
        raise HTTPException(status_code=404, detail="Pembelian not found")
    return pembelian

@router.post("", status_code=status.HTTP_201_CREATED)
async def create_pembelian(request: PembelianCreate, db: Session = Depends(get_db), user_name: str = Depends(get_current_user_name)):
    """Create new pembelian in DRAFT status - DOES NOT UPDATE STOCK YET"""

    
    # Create pembelian
    pembelian = Pembelian(
        no_pembelian=generate_unique_record_number(db, Pembelian, prefix="QP/PRC"),
        warehouse_id=request.warehouse_id,
        vendor_id=request.vendor_id,
        top_id=request.top_id,
        sales_date=request.sales_date,
        sumberdana_id=request.sumberdana_id,
        sales_due_date=request.sales_due_date,
        additional_discount=request.additional_discount or Decimal('0'),
        expense=request.expense or Decimal('0'),
        status_pembelian=StatusPembelianEnum.DRAFT,
        currency_amount = request.currency_amount or Decimal('0')
    )

    db.add(pembelian)
    db.flush()

    # Add items (no stock update in DRAFT)
    for item_request in request.items:
        # Validate item exists
        item = validate_item_exists(db, item_request.item_id)

        unit_price = (
            Decimal(str(item_request.unit_price))
            if item_request.unit_price is not None
            else Decimal(str(item.price))
        )
        unit_price_rmb = (
            Decimal(str(item_request.unit_price_rmb) )
            if item_request.unit_price_rmb is not None
            else Decimal(str(item.price))
        )

        pembelian_item = PembelianItem(
            pembelian_id=pembelian.id,
            item_id=item_request.item_id,
            qty=item_request.qty,
            unit_price=unit_price,
            unit_price_rmb=unit_price_rmb,
            tax_percentage=item_request.tax_percentage or 0,
            discount=item_request.discount or Decimal('0')
        )
        # Calculate totals for this item
        calculate_item_totals(pembelian_item)
        
        db.add(pembelian_item)

    db.commit()


    calculate_pembelian_totals(db, pembelian.id,user_name,"telah dibuat")

    return {
        "detail": "Pembelian created successfully",
        "id": pembelian.id,
    }

@router.put("/{pembelian_id}", response_model=PembelianResponse)
async def update_pembelian(
    pembelian_id: int,
    request: PembelianUpdate,
    db: Session = Depends(get_db),
    user_name: str = Depends(get_current_user_name)
):
    """Update pembelian - only updates stock if quantities change and pembelian is ACTIVE/PROCESSED"""
    
    # Load pembelian with items
    pembelian: Pembelian = (
        db.query(Pembelian)
        .options(selectinload(Pembelian.pembelian_items))
        .filter(Pembelian.id == pembelian_id)
        .first()
    )
    if not pembelian:
        raise HTTPException(status_code=404, detail="Pembelian not found")

    # Check if we can modify this pembelian
    validate_draft_status(pembelian)

    # Unique no_pembelian check
    if request.no_pembelian and request.no_pembelian != pembelian.no_pembelian:
        exists = db.query(Pembelian).filter(
            and_(Pembelian.no_pembelian == request.no_pembelian,
                 Pembelian.id != pembelian_id)
        ).first()
        if exists:
            raise HTTPException(status_code=400, detail="No pembelian already exists")

    # Apply simple field updates (non-items)
    update_data = request.dict(exclude_unset=True)
    items_data = update_data.pop("items", None)
    fields_changed = False
    for field, value in update_data.items():
        if getattr(pembelian, field, None) != value:
            setattr(pembelian, field, value)
            fields_changed = True

    # Items diff/update (only if payload provided)
    items_changed = False
    stock_adjustments = []  # Track stock changes: [(item_id, qty_change), ...]
    
    if items_data is not None:
        _validate_items_payload(items_data)

        # Build current items map
        current: dict[int, PembelianItem] = {pi.item_id: pi for pi in pembelian.pembelian_items}
        incoming_ids = set()

        for raw in items_data:
            d = _normalize_item_payload(raw)
            item_id = d["item_id"]
            incoming_ids.add(item_id)

            # Ensure the master Item exists
            item = validate_item_exists(db, item_id)

            if item_id in current:
                # Existing item - check for quantity changes
                pi = current[item_id]
                old_qty = int(pi.qty or 0)
                new_qty = d["qty"]
                
                # Track quantity changes for stock adjustment
                if old_qty != new_qty:
                    qty_change = new_qty - old_qty
                    stock_adjustments.append((item_id, qty_change))
                
                # Update item if anything changed
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
                    
                    # Recalculate item totals
                    calculate_item_totals(pi)
                    items_changed = True
            else:
                # New item - track as addition
                stock_adjustments.append((item_id, d["qty"]))  # New item = full quantity added
                
                new_item = PembelianItem(
                    pembelian_id=pembelian_id,
                    item_id=item.id,

                    qty=d["qty"],
                    unit_price=d["unit_price"],
                    tax_percentage=d["tax_percentage"],
                    discount=d["discount"],
                )
                
                # Calculate totals for new item
                calculate_item_totals(new_item)
                
                db.add(new_item)
                items_changed = True

        # Delete items that are no longer present
        for item_id, pi in list(current.items()):
            if item_id not in incoming_ids:
                # Track as removal (negative quantity change)
                stock_adjustments.append((item_id, -pi.qty))
                db.delete(pi)
                items_changed = True

        # Apply stock adjustments if pembelian is finalized (ACTIVE/PROCESSED)
        # For DRAFT pembelians, we don't touch stock until finalization
        if pembelian.status_pembelian in (StatusPembelianEnum.ACTIVE, StatusPembelianEnum.PROCESSED):
            for item_id, qty_change in stock_adjustments:
                if qty_change != 0:  # Only apply actual changes
                    update_item_stock(db, item_id, qty_change)

    # Commit and recalc totals if anything changed
    if fields_changed or items_changed:
        db.commit()
        calculate_pembelian_totals(db, pembelian_id,user_name, "telah diubah")
        db.commit()
    else:
        db.rollback()

    return await get_pembelian(pembelian_id, db)

@router.patch("/{pembelian_id}", status_code=status.HTTP_200_OK)
async def rollback_pembelian_status(pembelian_id: int, db: Session = Depends(get_db), user_name : str  = Depends(get_current_user_name)):
    """
    Rolls back the status of a purchase ('Pembelian') to 'DRAFT'
    if its current status is 'ACTIVE' or 'COMPLETED'.
    Also reverses stock changes by subtracting the quantities.
    """
    audit_service  = AuditService(db)

    pembelian = (
        db.query(Pembelian)
        .options(selectinload(Pembelian.pembelian_items))
        .filter(Pembelian.id == pembelian_id)
        .first()
    )

    if not pembelian:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pembelian not found")

    if pembelian.status_pembelian in (StatusPembelianEnum.ACTIVE, StatusPembelianEnum.COMPLETED):
        for pembelian_item in pembelian.pembelian_items:
            update_item_stock(db, pembelian_item.item_id, -pembelian_item.qty)
        
        pembelian.status_pembelian = StatusPembelianEnum.DRAFT

        pembelian.warehouse_name = None
        pembelian.vendor_name = None
        pembelian.vendor_address = None
        pembelian.top_name = None
        pembelian.currency_name = None
    
    db.commit()

    audit_service.default_log(
        entity_id=pembelian.id,
        entity_type=AuditEntityEnum.PEMBELIAN,
        description=f"Pembelian {pembelian.no_pembelian} status transaksi diubah: Aktif → Draft",
        user_name=user_name
    )
    return {
        "msg": "Pembelian status changed successfully"
    }

@router.post("/{pembelian_id}/finalize", response_model=PembelianResponse)
async def finalize_pembelian_endpoint(pembelian_id: int, db: Session = Depends(get_db), user_name : str  = Depends(get_current_user_name)):
    """Finalize pembelian - convert from DRAFT to ACTIVE and update stock"""
    finalize_pembelian(db, pembelian_id, user_name)
    return await get_pembelian(pembelian_id, db)

@router.put("/{pembelian_id}/status", response_model=PembelianResponse)
async def update_status(
        pembelian_id: int,
        request: PembelianStatusUpdate,
        db: Session = Depends(get_db)
):
    """Update pembelian status"""

    pembelian = db.query(Pembelian).filter(Pembelian.id == pembelian_id).first()
    if not pembelian:
        raise HTTPException(status_code=404, detail="Pembelian not found")

    # Update status fields
    if request.status_pembelian:
        pembelian.status_pembelian = request.status_pembelian
    if request.status_pembayaran:
        pembelian.status_pembayaran = request.status_pembayaran

    db.commit()
    return await get_pembelian(pembelian_id, db)

@router.post("/{pembelian_id}/upload-attachments", response_model=UploadResponse)
async def upload_attachments(
        pembelian_id: str,
        files: List[UploadFile] = File(...),
        db: Session = Depends(get_db)
):
    """Upload multiple attachment files for pembelian"""

    pembelian = db.query(Pembelian).filter(Pembelian.id == pembelian_id).first()
    if not pembelian:
        raise HTTPException(status_code=404, detail="Pembelian not found")

    uploaded_files = []

    for file in files:
        # Validate file type
        if file.content_type not in ALLOWED_FILE_TYPES:
            raise HTTPException(
                status_code=400,
                detail=f"File type {file.content_type} not allowed. Only PDF, JPG, PNG files are allowed."
            )

        # Save file
        file_path = save_uploaded_file(file, pembelian_id)

        attachment = AllAttachment(
            parent_type=ParentType.PEMBELIANS,
            pembelian_id=pembelian_id,
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

@router.delete("/{pembelian_id}/attachments/{attachment_id}", response_model=SuccessResponse)
async def delete_attachment(
        pembelian_id: str,
        attachment_id: int,
        db: Session = Depends(get_db)
):
    """Delete specific attachment"""

    attachment = db.query(AllAttachment).filter(
        and_(
            AllAttachment.id == attachment_id,
            AllAttachment.pembelian_id == pembelian_id
        )
    ).first()

    if not attachment:
        raise HTTPException(status_code=404, detail="Attachment not found")

    # Delete file from filesystem
    if os.path.exists(attachment.file_path):
        os.remove(attachment.file_path)

    # Delete database record
    db.delete(attachment)
    db.commit()

    return SuccessResponse(message="Attachment deleted successfully")

@router.get("/{pembelian_id}/download/{attachment_id}")
async def download_attachment(
        pembelian_id: str,
        attachment_id: int,
        db: Session = Depends(get_db)
):
    """Download attachment file"""

    attachment = db.query(AllAttachment).filter(
        and_(
            AllAttachment.id == attachment_id,
            AllAttachment.pembelian_id == pembelian_id
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


@router.get("/{pembelian_id}/totals", response_model=TotalsResponse)
async def get_totals(pembelian_id: int, db: Session = Depends(get_db)):
    data = calculate_pembelian_totals(db, pembelian_id)
    return TotalsResponse(**data)

@router.post("/{pembelian_id}/recalculate", response_model=TotalsResponse)
async def recalc_totals(pembelian_id: int, db: Session = Depends(get_db)):
    data = calculate_pembelian_totals(db, pembelian_id)
    return TotalsResponse(**data)

@router.delete("/{pembelian_id}", response_model=SuccessResponse)
async def delete_pembelian(pembelian_id: int, db: Session = Depends(get_db)):
    """
    Delete pembelian:
      - If DRAFT and no payments -> HARD DELETE (doc + lines + files).
      - If any payments exist OR not DRAFT -> either block OR soft delete (archive).
        (Below: we choose to SOFT DELETE to keep payments and lines.)
    """
    pembelian = (
        db.query(Pembelian)
        .options(
            selectinload(Pembelian.pembelian_items),
            selectinload(Pembelian.attachments),
            selectinload(Pembelian.pembayaran_detail_rel),
        )
        .get(pembelian_id)
    )

    if not pembelian:
        raise HTTPException(status_code=404, detail="Pembelian not found")

    has_payments = bool(pembelian.pembayaran_detail_rel)

    if pembelian.status_pembelian.name == "DRAFT" and not has_payments:
        try:
            for att in pembelian.attachments:
                if att.file_path and os.path.exists(att.file_path):
                    try:
                        os.remove(att.file_path)
                    except Exception:
                        pass

            db.query(PembelianItem).filter(
                PembelianItem.pembelian_id == pembelian_id
            ).delete(synchronize_session=False)

            db.query(AllAttachment).filter(
                AllAttachment.pembelian_id == pembelian_id
            ).delete(synchronize_session=False)
            db.delete(pembelian)
            db.commit()
            return SuccessResponse(message="Pembelian (DRAFT) deleted successfully")
        except Exception as e:
            db.rollback()
            raise HTTPException(
                status_code=500,
                detail=f"Error deleting pembelian: {str(e)}"
            )

    # Otherwise -> SOFT DELETE (archive). Keep items & payments.
    try:
        pembelian.is_deleted = True
        pembelian.deleted_at = datetime.utcnow()
        db.commit()
        return SuccessResponse(
            message="Pembelian archived (soft deleted). Items and payments preserved."
        )
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Error archiving pembelian: {str(e)}"
        )

# Statistics endpoints
@router.get("/stats/summary")
async def get_pembelian_summary(db: Session = Depends(get_db)):
    """Get pembelian statistics summary"""

    total_count = db.query(func.count(Pembelian.id)).scalar()
    draft_count = db.query(func.count(Pembelian.id)).filter(
        Pembelian.status_pembelian == StatusPembelianEnum.DRAFT
    ).scalar()
    active_count = db.query(func.count(Pembelian.id)).filter(
        Pembelian.status_pembelian == StatusPembelianEnum.ACTIVE
    ).scalar()
    completed_count = db.query(func.count(Pembelian.id)).filter(
        Pembelian.status_pembelian == StatusPembelianEnum.COMPLETED
    ).scalar()

    total_value = db.query(func.sum(Pembelian.total_price)).scalar() or 0
    unpaid_value = db.query(func.sum(Pembelian.total_price)).filter(
        Pembelian.status_pembayaran == StatusPembayaranEnum.UNPAID
    ).scalar() or 0

    return {
        "total_pembelian": total_count,
        "draft_count": draft_count,
        "active_count": active_count,
        "completed_count": completed_count,
        "total_value": total_value,
        "unpaid_value": unpaid_value
    }

# First, add these calculation functions for Pembelian (similar to Penjualan)

def calculate_pembelian_item_totals(item: PembelianItem) -> None:
    """
    Calculate pembelian item totals following the exact frontend logic:
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


# Updated Pembelian Invoice Endpoint
@router.get("/{pembelian_id}/invoice/html", response_class=HTMLResponse)
async def view_pembelian_invoice_html(pembelian_id: int, request: Request, db: Session = Depends(get_db)):
    pembelian = (
        db.query(Pembelian)
        .options(
            joinedload(Pembelian.pembelian_items)
            .joinedload(PembelianItem.item_rel)
            .joinedload(Item.attachments)
        )
        .filter(Pembelian.id == pembelian_id)
        .first()
    )
    if not pembelian:
        raise HTTPException(status_code=404, detail="Pembelian not found")

    BASE_URL = os.getenv("BASE_URL", "http://localhost:8000")

    # Use the fixed calculation function to ensure consistency
    totals_data = calculate_pembelian_totals(db, pembelian_id)

    enhanced_items = []
    
    for it in pembelian.pembelian_items:
        # FIXED: Use primary_image_url which returns raw path, not full URL
        raw_image_path = it.primary_image_url if it.item_rel else None
        img_url = get_public_image_url(raw_image_path, BASE_URL) if raw_image_path else None
        
        # Use the calculate_pembelian_item_totals function to ensure consistency
        calculate_pembelian_item_totals(it)
        
        # Extract calculated values from the item
        qty = Decimal(str(it.qty or 0))
        unit_price = Decimal(str(it.unit_price or 0))
        tax_pct = Decimal(str(it.tax_percentage or 0))
        item_discount = Decimal(str(it.discount or 0))
        
        # Calculate using the same frontend logic as the fixed function
        row_sub_total = qty * unit_price  # Before any discounts/tax
        taxable_base = max(row_sub_total - item_discount, Decimal('0'))
        item_tax = (taxable_base * tax_pct) / Decimal('100')
        item_total_price = taxable_base + item_tax
        
        # FIXED: Use it.item_rel.name instead of it.item_name
        item_name = it.item_rel.name if it.item_rel else "Unknown Item"
        satuan_name = it.item_rel.satuan_rel.name if it.item_rel.satuan_rel else "Unknown Satuan"
        
        enhanced_items.append({
            "item": it,
            "image_url": img_url,
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
        })

    # Get additional values from pembelian
    additional_discount = Decimal(str(pembelian.additional_discount or 0))
    expense = Decimal(str(pembelian.expense or 0))

    # Use the calculated totals from the function to ensure consistency
    totals = {
        "subtotal": totals_data["total_subtotal"],
        "item_discounts": totals_data["total_discount"],
        "additional_discount": additional_discount,
        "subtotal_after_discounts": totals_data["subtotal_after_item_discounts"],
        "final_total": totals_data["total_before_discount"],
        "tax_amount": totals_data["total_tax"],
        "expense": expense,
        "grand_total": totals_data["total_price"],
        # Keep backward compatibility
        "subtotal_before_tax": totals_data["total_subtotal"],
        "total_item_discounts": totals_data["total_discount"],
        "total_before_tax": totals_data["total_before_discount"],
    }

    return templates.TemplateResponse(
        "pembelian.html",
        {
            "request": request,
            "pembelian": pembelian,
            "enhanced_items": enhanced_items,
            "totals": totals,
            "company": {
                "name": "PT. Jayagiri Indo Asia",
                "logo_url": get_public_image_url("logo.png", BASE_URL),
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