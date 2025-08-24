import mimetypes
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
from decimal import Decimal

from starlette.responses import HTMLResponse

from database import get_db
from starlette.requests import Request
from models.Vendor import Vendor  # Changed from Customer to Vendor
from models.Item import Item
from models.Pembelian import Pembelian, StatusPembelianEnum,PembelianItem, StatusPembayaranEnum
from models.AllAttachment import ParentType, AllAttachment
from routes.upload_routes import to_public_image_url, templates
from schemas.PaginatedResponseSchemas import PaginatedResponse
from schemas.PembelianSchema import TotalsResponse, PembelianListResponse, PembelianResponse, PembelianCreate, \
    PembelianUpdate, PembelianStatusUpdate, UploadResponse, SuccessResponse
from utils import generate_unique_record_number

router = APIRouter()

# Configuration
UPLOAD_DIR = os.getenv("STATIC_URL")
os.makedirs(UPLOAD_DIR, exist_ok=True)
ALLOWED_FILE_TYPES = ["application/pdf", "image/jpeg", "image/png", "image/jpg"]
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB

# Utility Functions
def generate_pembelian_id() -> int:
    return random.randint(10000000, 99999999)

def calculate_item_total(qty: int, unit_price: Decimal) -> Decimal:
    """Calculate total price for an item"""
    return Decimal(str(qty)) * unit_price

def validate_item_stock(db: Session, item_id: str, requested_qty: int) -> None:
    """Validate if requested quantity is available in stock"""
    item = db.query(Item).filter(Item.id == item_id).first()

    if not item:
        raise HTTPException(
            status_code=404,
            detail=f"Item with ID {item_id} not found"
        )

    # Get current available stock (handle None case)
    available_stock = item.total_item if item.total_item is not None else 0

    # Check if we have enough stock
    if available_stock < requested_qty:
        raise HTTPException(
            status_code=400,
            detail=f"Stock untuk item '{item.name}' tidak tersedia. Available: {available_stock}, Requested: {requested_qty}"
        )

    # Check if stock would go positive 
    remaining_after_addition = available_stock + requested_qty
   

def validate_pembelian_items_stock(db: Session, items_data: List) -> None:
    """Validate stock for all items in pembelian"""
    for item_data in items_data:
        if hasattr(item_data, 'item_id') and hasattr(item_data, 'qty'):
            # For Pydantic models
            validate_item_stock(db, item_data.item_id, item_data.qty)
        elif isinstance(item_data, dict):
            # For dictionary data
            validate_item_stock(db, item_data['item_id'], item_data['qty'])
def calculate_pembelian_totals(db: Session, pembelian_id: int):
    items = (
        db.query(PembelianItem)
        .filter(PembelianItem.pembelian_id == pembelian_id)
        .all()
    )

    q = Decimal('0')
    sum_before_tax = Decimal('0')
    sum_after_tax = Decimal('0')
    total_item_discounts = Decimal('0')  # Sum of all individual item discounts

    for it in items:
        qty = Decimal(it.qty or 0)
        unit_after_tax = Decimal(it.unit_price or 0)
        tax_pct = Decimal(it.tax_percentage or 0)
        item_discount = Decimal(it.discount or 0)  # This is the discount amount per item

        # unit price before tax = after / (1 + tax%)
        unit_before_tax = unit_after_tax / (Decimal(1) + (tax_pct / Decimal(100)))

        # Calculate totals
        item_subtotal_before_tax = qty * unit_before_tax
        item_subtotal_after_tax = qty * unit_after_tax

        q += qty
        sum_before_tax += item_subtotal_before_tax
        sum_after_tax += item_subtotal_after_tax
        total_item_discounts += item_discount  # Add individual item discount

    pembelian = db.query(Pembelian).filter(Pembelian.id == pembelian_id).first()

    # Get additional discount (this is separate from item discounts)
    additional_discount = Decimal(pembelian.additional_discount or 0)
    expense = Decimal(pembelian.expense or 0)

    # Calculate tax amount
    tax_amount = sum_after_tax - sum_before_tax

    # Calculate total after discounts but before tax
    # Total = Sum(qty * price_before_tax) - Sum(item_discounts) - additional_discount
    total_before_tax = sum_before_tax - total_item_discounts - additional_discount

    # Grand total = total_before_tax + tax + expense
    grand_total = total_before_tax + tax_amount + expense

    # Update pembelian totals
    pembelian.total_qty = int(q)
    pembelian.total_price = grand_total
    db.commit()

    return {
        "subtotal_before_tax": sum_before_tax,
        "subtotal_after_tax": sum_after_tax,
        "tax_amount": tax_amount,
        "total_item_discounts": total_item_discounts,  # Changed from discount_amount
        "additional_discount": additional_discount,
        "expense": expense,
        "total_qty": int(q),
        "total_before_tax": total_before_tax,  # Added this field
        "grand_total": grand_total,
    }


def finalize_pembelian(db: Session, pembelian_id: str):
    pembelian = db.query(Pembelian).options(
        selectinload(Pembelian.warehouse_rel),
        selectinload(Pembelian.vend_rel).selectinload(Vendor.curr_rel),  # Changed: Load vendor with currency relationship
        selectinload(Pembelian.top_rel),
        selectinload(Pembelian.pembelian_items).selectinload(PembelianItem.item_rel)
    ).filter(Pembelian.id == pembelian_id).first()

    if not pembelian:
        raise HTTPException(status_code=404, detail="Pembelian not found")

    if pembelian.status_pembelian != StatusPembelianEnum.DRAFT:
        raise HTTPException(status_code=400, detail="Can only finalize DRAFT pembelians")

    # Validate required fields - Changed: vendor_id instead of customer_id
    if not pembelian.warehouse_id or not pembelian.vendor_id:
        raise HTTPException(status_code=400, detail="Warehouse and Vendor are required for finalization")

    if not pembelian.pembelian_items:
        raise HTTPException(status_code=400, detail="At least one item is required for finalization")

    # STOCK VALIDATION - Check stock availability for all items
    for pembelian_item in pembelian.pembelian_items:
        validate_item_stock(db, pembelian_item.item_id, pembelian_item.qty)

    # Copy master data names
    if pembelian.warehouse_rel:
        pembelian.warehouse_name = pembelian.warehouse_rel.name
    if pembelian.vend_rel:  # Changed: vendor instead of customer
        pembelian.vendor_name = pembelian.vend_rel.name
        pembelian.vendor_address = pembelian.vend_rel.address

        # Get currency name from vendor's currency relationship
        if pembelian.vend_rel.curr_rel:
            pembelian.currency_name = pembelian.vend_rel.curr_rel.name
    if pembelian.top_rel:
        pembelian.top_name = pembelian.top_rel.name

    # Copy item data
    for pembelian_item in pembelian.pembelian_items:
        if pembelian_item.item_rel:
            item = pembelian_item.item_rel
            pembelian_item.item_name = item.name
            pembelian_item.item_sku = item.sku
            pembelian_item.item_type = item.type.value if item.type else None
            if item.satuan_rel:
                pembelian_item.satuan_name = item.satuan_rel.name


    # Update item stock after validation - add the quantities
    for pembelian_item in pembelian.pembelian_items:
        item = db.query(Item).filter(Item.id == pembelian_item.item_id).first()
        if item and item.total_item is not None:
            # Add the purchased quantity from available stock
            item.total_item = item.total_item + pembelian_item.qty

    # Update status
    pembelian.status_pembelian = StatusPembelianEnum.ACTIVE
    db.commit()

def validate_draft_status(pembelian: Pembelian):
    """Validate that pembelian is in DRAFT status for editing"""
    if pembelian.status_pembelian != StatusPembelianEnum.DRAFT:
        raise HTTPException(
            status_code=400,
            detail="Can only modify DRAFT pembelians"
        )

def save_uploaded_file(file: UploadFile, pembelian_id: str) -> str:
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

# API Endpoints

@router.get("", response_model=PaginatedResponse[PembelianListResponse])
async def get_all_pembelian(
        status_pembelian: Optional[StatusPembelianEnum] = Query(None),
        status_pembayaran: Optional[StatusPembayaranEnum] = Query(None),
        vendor_id: Optional[str] = Query(None),  # Changed: vendor_id instead of customer_id
        warehouse_id: Optional[int] = Query(None),
        page: int = Query(1, ge=1),
        size: int = Query(50, ge=1, le=100),
        db: Session = Depends(get_db)
):
    """Get all pembelian with filtering and pagination"""

    query = db.query(Pembelian).options(
        selectinload(Pembelian.pembelian_items),
        selectinload(Pembelian.attachments),
        selectinload(Pembelian.vend_rel),  # Changed: vendor relationship
        selectinload(Pembelian.warehouse_rel)
    ).filter(Pembelian.is_deleted== False)

    # Apply filters
    if status_pembelian is not None and status_pembelian != StatusPembelianEnum.ALL:
        if status_pembelian == StatusPembelianEnum.ACTIVE or status_pembelian == StatusPembelianEnum.PROCESSED:
             query = query.filter(
            (Pembelian.status_pembelian == StatusPembelianEnum.ACTIVE) |
            (Pembelian.status_pembelian == StatusPembelianEnum.PROCESSED)
        )
        else :
            query = query.filter(Pembelian.status_pembelian == status_pembelian)
            
    if status_pembayaran is not None and status_pembayaran != StatusPembayaranEnum.ALL:
        query = query.filter(Pembelian.status_pembayaran == status_pembayaran)
    if vendor_id:  # Changed: vendor_id filter
        query = query.filter(Pembelian.vendor_id == vendor_id)
    if warehouse_id:
        query = query.filter(Pembelian.warehouse_id == warehouse_id)

    offset = (page - 1) * size
    pembelians = query.order_by(desc(Pembelian.sales_date)).offset(offset).limit(size).all()

    result = []
    for pembelian in pembelians:
        vendor_name = pembelian.vendor_name
        if not vendor_name and pembelian.vend_rel:
            vendor_name = pembelian.vend_rel.name

        warehouse_name = pembelian.warehouse_name
        if not warehouse_name and pembelian.warehouse_rel:
            warehouse_name = pembelian.warehouse_rel.name

        pembelian_dict = {
            "id": pembelian.id,
            "no_pembelian": pembelian.no_pembelian,
            "status_pembayaran": pembelian.status_pembayaran,
            "status_pembelian": pembelian.status_pembelian,
            "sales_date": pembelian.sales_date,
            "total_paid": pembelian.total_paid.quantize(Decimal('0.0001')),
            "total_return": pembelian.total_return.quantize(Decimal('0.0001')),
            
            "total_qty": pembelian.total_qty,
            "total_price": pembelian.total_price.quantize(Decimal('0.0001')),
            "vendor_name": vendor_name,  # Changed: vendor_name instead of customer_name
            "warehouse_name": warehouse_name,
            "items_count": len(pembelian.pembelian_items),
            "attachments_count": len(pembelian.attachments)
        }
        result.append(PembelianListResponse(**pembelian_dict))

    return {
        "data": result,
        "total": query.count(),
    }

@router.get("/{pembelian_id}", response_model=PembelianResponse)
async def get_pembelian(pembelian_id: int, db: Session = Depends(get_db)): 
    pembelian = (
        db.query(Pembelian)
          .options(
              selectinload(Pembelian.pembelian_items)
                  .selectinload(PembelianItem.item_rel),   # <- this loads Item by item_id
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
async def create_pembelian(request: PembelianCreate, db: Session = Depends(get_db)):
    """Create new pembelian in DRAFT status"""

    # Check if no_pembelian already exists
    existing = db.query(Pembelian).filter(Pembelian.no_pembelian == request.no_pembelian).first()
    if existing:
        raise HTTPException(status_code=400, detail="No pembelian sudah ada")

    validate_pembelian_items_stock(db, request.items)

    pembelian = Pembelian(
        id=generate_pembelian_id(),
        no_pembelian = generate_unique_record_number(db, Pembelian, prefix="QP/AP"),
        warehouse_id=request.warehouse_id,
        vendor_id=request.vendor_id,
        top_id=request.top_id,
        sales_date=request.sales_date,
        sales_due_date=request.sales_due_date,
        
        additional_discount=request.additional_discount,
        expense=request.expense,
        status_pembelian=StatusPembelianEnum.DRAFT
    )

    db.add(pembelian)
    db.flush()
    for item_request in request.items:
        item = db.query(Item).filter(Item.id == item_request.item_id).first()
        if not item:
            raise HTTPException(
                status_code=404,
                detail=f"Item with ID {item_request.item_id} not found"
            )

        unit_price = (
        Decimal(str(item_request.unit_price))
        if item_request.unit_price is not None
        else Decimal(str(item.price))
)
        total_price = calculate_item_total(item_request.qty, unit_price)
        new_item = db.query(Item).filter(Item.id == item_request.item_id).first()

        pembelian_item = PembelianItem(
            pembelian_id=pembelian.id,
            item_id=item_request.item_id,
            discount=item_request.discount,
            item_name=new_item.name,
            qty=item_request.qty,
            unit_price=unit_price,
            tax_percentage=item_request.tax_percentage,
            total_price=total_price
        )
        db.add(pembelian_item)

    db.commit()

    # Calculate totals
    calculate_pembelian_totals(db, pembelian.id)

    return {
        "detail": "Pembelian created successfully",
        "id": pembelian.id,
    }

@router.put("/{pembelian_id}", response_model=PembelianResponse)
async def update_pembelian(
    pembelian_id: int,
    request: PembelianUpdate,
    db: Session = Depends(get_db),
):
    # 1) Load + guard
    pembelian = db.query(Pembelian).filter(Pembelian.id == pembelian_id).first()
    if not pembelian:
        raise HTTPException(status_code=404, detail="Pembelian not found")
    validate_draft_status(pembelian)

    # 2) Unique no_pembelian check
    if request.no_pembelian and request.no_pembelian != pembelian.no_pembelian:
        exists = db.query(Pembelian).filter(
            and_(Pembelian.no_pembelian == request.no_pembelian,
                 Pembelian.id != pembelian_id)
        ).first()
        if exists:
            raise HTTPException(status_code=400, detail="No pembelian already exists")

    # 3) Apply simple field updates
    update_data = request.dict(exclude_unset=True)  # or request.model_dump(exclude_unset=True) for pydantic v2
    items_data = update_data.pop("items", None)
    for field, value in update_data.items():
        setattr(pembelian, field, value)

    if items_data is not None:
        validate_pembelian_items_stock(db, items_data)

        db.query(PembelianItem).filter(
            PembelianItem.pembelian_id == pembelian_id
        ).delete()

        for item_req in items_data:
            item = db.query(Item).filter(Item.id == item_req["item_id"]).first()
            if not item:
                raise HTTPException(
                    status_code=404,
                    detail=f"Item with ID {item_req['item_id']} not found",
                )

            # unit_price is REQUIRED by schema on update – no fallback
            unit_price = Decimal(str(item_req["unit_price"]))
            qty = int(item_req["qty"])
            tax_percentage = int(item_req.get("tax_percentage", 0))

            total_price = calculate_item_total(qty, unit_price)

            db.add(PembelianItem(
                pembelian_id=pembelian_id,
                item_id=item.id,
                item_name=item.name,
                qty=qty,
                unit_price=unit_price,        
                total_price=total_price,
                tax_percentage=tax_percentage,
            ))

    db.commit()
    calculate_pembelian_totals(db, pembelian_id)
    db.commit()

    return await get_pembelian(pembelian_id, db)


@router.patch("/{pembelian_id}", status_code=status.HTTP_200_OK)
async def rollback_pembelian_status(pembelian_id: int, db: Session = Depends(get_db)):
    """
    Rolls back the status of a purchase ('Pembelian') to 'DRAFT'
    if its current status is 'ACTIVE' or 'COMPLETED'.
    
    Args:
        pembelian_id: The unique ID of the purchase to update.
        db: The database session dependency.
    """

    query = db.query(Pembelian).filter(Pembelian.id == pembelian_id)

    pembelian = query.first()

    if not pembelian:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pembelian not found")


    if pembelian.status_pembelian in (StatusPembelianEnum.ACTIVE, StatusPembelianEnum.COMPLETED):
        pembelian.status_pembelian = StatusPembelianEnum.DRAFT
    
    db.commit()
    db.refresh(pembelian)
    return {
        "msg": "Pembelian status changed successfully"
    }

@router.post("/{pembelian_id}/finalize", response_model=PembelianResponse)
async def finalize_pembelian_endpoint(pembelian_id: str, db: Session = Depends(get_db)):
    """Finalize pembelian - convert from DRAFT to ACTIVE"""

    finalize_pembelian(db, pembelian_id)
    return await get_pembelian(pembelian_id, db)

@router.put("/{pembelian_id}/status", response_model=PembelianResponse)
async def update_status(
        pembelian_id: str,
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

    BASE_URL = os.getenv("BASE_URL", "https://qiu-system.qiuparts.com")

    enhanced_items = []
    subtotal_before_tax = Decimal('0')
    total_item_discounts = Decimal('0')
    tax_amount = Decimal('0')
    
    for it in pembelian.pembelian_items:
        raw = it.item_rel.primary_image_url if it.item_rel else None
        img_url = to_public_image_url(raw, request, BASE_URL)
        
        # Calculate item totals
        qty = Decimal(str(it.qty or 0))
        unit_price_after_tax = Decimal(str(it.unit_price or 0))
        tax_pct = Decimal(str(it.tax_percentage or 0))
        item_discount = Decimal(str(it.discount or 0))
        
        # Calculate unit price before tax
        unit_price_before_tax = unit_price_after_tax / (Decimal(1) + (tax_pct / Decimal(100)))
        
        # Calculate item subtotal before tax
        item_subtotal_before_tax = qty * unit_price_before_tax
        
        # Calculate item tax
        item_tax = item_subtotal_before_tax * (tax_pct / Decimal(100))
        
        enhanced_items.append({
            "item": it,
            "image_url": img_url,
            "item_name": it.item_name,
            "qty": it.qty,
            "satuan_name": it.satuan_name,
            "tax_percentage": it.tax_percentage,
            "unit_price_before_tax": unit_price_before_tax,
            "unit_price": it.unit_price,
            "item_discount": item_discount,
            "item_subtotal_before_tax": item_subtotal_before_tax,
            "item_tax": item_tax,
            "total_price": it.total_price,
        })
        
        subtotal_before_tax += item_subtotal_before_tax
        total_item_discounts += item_discount
        tax_amount += item_tax

    # Calculate additional discount and final totals
    additional_discount = Decimal(str(pembelian.additional_discount or 0))
    expense = Decimal(str(pembelian.expense or 0))
    
    # Total after item discounts and additional discount, before tax
    total_before_tax = subtotal_before_tax - total_item_discounts - additional_discount
    
    # Grand total
    grand_total = total_before_tax + tax_amount + expense

    totals = {
        "subtotal_before_tax": subtotal_before_tax,
        "total_item_discounts": total_item_discounts,
        "additional_discount": additional_discount,
        "total_before_tax": total_before_tax,
        "tax_amount": tax_amount,
        "expense": expense,
        "grand_total": grand_total,
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
                "logo_url": "static/logo.png",
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