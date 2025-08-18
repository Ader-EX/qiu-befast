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

from starlette.requests import Request
from starlette.responses import HTMLResponse

from database import get_db
from models.Customer import Customer
from models.Pembayaran import  Pembayaran
from models.Penjualan import StatusPembayaranEnum, StatusPembelianEnum
from models.Penjualan import Penjualan, PenjualanItem

from models.Item import Item

from models.AllAttachment import ParentType, AllAttachment
from routes.upload_routes import to_public_image_url, templates
from schemas.PaginatedResponseSchemas import PaginatedResponse
from schemas.PenjualanSchema import PenjualanCreate, PenjualanListResponse, PenjualanResponse, PenjualanStatusUpdate, PenjualanUpdate, SuccessResponse, TotalsResponse, UploadResponse
from utils import generate_unique_record_number

router = APIRouter()

# Configuration
UPLOAD_DIR = os.getenv("STATIC_URL")
os.makedirs(UPLOAD_DIR, exist_ok=True)
ALLOWED_FILE_TYPES = ["application/pdf", "image/jpeg", "image/png", "image/jpg"]
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB

# Utility Functions
def generate_penjualan_id() -> int:
    return random.randint(10000000, 999999999)

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

    available_stock = item.total_item if item.total_item is not None else 0

    if available_stock < requested_qty:
        raise HTTPException(
            status_code=400,
            detail=f"Stock untuk item '{item.name}' tidak tersedia. Tersedia: {available_stock}, Requested: {requested_qty}"
        )

    remaining_after_deduction = available_stock - requested_qty
    if remaining_after_deduction < 0:
        raise HTTPException(
            status_code=400,
            detail=f"Stock akan menjadi < 0 untuk item '{item.name}'. Tersedia: {available_stock}, Requested: {requested_qty}"
        )

def validate_penjualan_items_stock(db: Session, items_data: List) -> None:
    """Validate stock for all items in penjualan"""
    for item_data in items_data:
        if hasattr(item_data, 'item_id') and hasattr(item_data, 'qty'):
            # For Pydantic models
            validate_item_stock(db, item_data.item_id, item_data.qty)
        elif isinstance(item_data, dict):
            # For dictionary data
            validate_item_stock(db, item_data['item_id'], item_data['qty'])

def calculate_penjualan_totals(db: Session, penjualan_id: int):
    items = (
        db.query(PenjualanItem)
        .filter(PenjualanItem.penjualan_id == penjualan_id)
        .all()
    )

    q = Decimal('0')
    sum_before = Decimal('0')
    sum_after  = Decimal('0')

    for it in items:
        qty = Decimal(it.qty or 0)
        unit_after = Decimal(it.unit_price or 0)
        tax_pct = Decimal(it.tax_percentage or 0)

        before_unit = unit_after / (Decimal(1) + (tax_pct / Decimal(100)))

        q += qty
        sum_before += qty * before_unit
        sum_after  += qty * unit_after

    penjualan = db.query(Penjualan).filter(Penjualan.id == penjualan_id).first()

    discount_percent = Decimal(penjualan.discount or 0)
    additional_discount = Decimal(penjualan.additional_discount or 0)
    expense = Decimal(penjualan.expense or 0)

    tax_amount = sum_after - sum_before
    discount_amount = (sum_before * discount_percent) / Decimal(100)

    grand_total = sum_before - discount_amount - additional_discount + tax_amount + expense

    penjualan.total_qty = int(q)
    penjualan.total_price = grand_total
    db.commit()

    return {
        "subtotal_before_tax": sum_before,
        "subtotal_after_tax": sum_after,
        "tax_amount": tax_amount,
        "discount_percent": discount_percent,
        "discount_amount": discount_amount,
        "additional_discount": additional_discount,
        "expense": expense,
        "total_qty": int(q),
        "grand_total": grand_total,
    }

def finalize_penjualan(db: Session, penjualan_id: int):
    penjualan = (
        db.query(Penjualan)
        .options(
            selectinload(Penjualan.warehouse_rel),
            selectinload(Penjualan.customer_rel).selectinload(Customer.curr_rel),
            selectinload(Penjualan.top_rel),
            selectinload(Penjualan.penjualan_items).selectinload(PenjualanItem.item_rel),
        )
        .filter(Penjualan.id == penjualan_id)
        .first()
    )

    if not penjualan:
        raise HTTPException(status_code=404, detail="penjualan not found")
    if penjualan.status_penjualan != StatusPembelianEnum.DRAFT:
        raise HTTPException(status_code=400, detail="Can only finalize DRAFT penjualans")
    if not penjualan.warehouse_id or not penjualan.customer_id:
        raise HTTPException(status_code=400, detail="Warehouse and Customer are required for finalization")
    if not penjualan.penjualan_items:
        raise HTTPException(status_code=400, detail="At least one item is required for finalization")

    # PRESERVE the original no_penjualan
    original_no_penjualan = penjualan.no_penjualan

    for it in penjualan.penjualan_items:
        validate_item_stock(db, it.item_id, it.qty)

    if penjualan.warehouse_rel:
        penjualan.warehouse_name = penjualan.warehouse_rel.name

    cust = penjualan.customer_rel
    if cust:
        if hasattr(penjualan, "customer_name"):
            penjualan.customer_name = cust.name
        if hasattr(penjualan, "customer_address"):
            penjualan.customer_address = getattr(cust, "address", None)
        if hasattr(penjualan, "currency_name") and getattr(cust, "curr_rel", None):
            penjualan.currency_name = cust.curr_rel.name

    if penjualan.top_rel and hasattr(penjualan, "top_name"):
        penjualan.top_name = penjualan.top_rel.name

    for pit in penjualan.penjualan_items:
        item = pit.item_rel
        if item:
            pit.item_name = item.name
            pit.item_sku = item.sku
            pit.item_type = item.type.value if getattr(item, "type", None) else None
            if getattr(item, "satuan_rel", None):
                pit.satuan_name = item.satuan_rel.name
            if getattr(item, "customer_rel", None):
                pit.customer_name = item.customer_rel.name

 
    if not penjualan.no_penjualan or penjualan.no_penjualan != original_no_penjualan:
        penjualan.no_penjualan = original_no_penjualan

    for pit in penjualan.penjualan_items:
        item = db.query(Item).filter(Item.id == pit.item_id).first()
        if item is not None and item.total_item is not None:
            item.total_item = item.total_item - pit.qty

    penjualan.status_penjualan = StatusPembelianEnum.ACTIVE
    
    if not penjualan.no_penjualan:
        penjualan.no_penjualan = original_no_penjualan
    
    db.commit()


def validate_draft_status(penjualan: Penjualan):
    """Validate that penjualan is in DRAFT status for editing"""
    if penjualan.status_penjualan != StatusPembelianEnum.DRAFT:
        raise HTTPException(
            status_code=400,
            detail="Can only modify DRAFT penjualans"
        )

def save_uploaded_file(file: UploadFile, penjualan_id: str) -> str:
    """Save uploaded file and return file path"""
    if file.size > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"File size too large. Maximum size is {MAX_FILE_SIZE // (1024*1024)}MB"
        )

    file_extension = os.path.splitext(file.filename)[1]
    unique_filename = f"{penjualan_id}_{uuid.uuid4().hex[:8]}{file_extension}"
    file_path = os.path.join(UPLOAD_DIR, unique_filename)

    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    return file_path

# API Endpoints

@router.get("", response_model=PaginatedResponse[PenjualanListResponse])
async def get_all_penjualan(
        status_penjualan: Optional[StatusPembelianEnum] = Query(None),
        status_pembayaran: Optional[StatusPembayaranEnum] = Query(None),
        customer_id: Optional[str] = Query(None),  # Changed: customer_id instead of customer_id
        warehouse_id: Optional[int] = Query(None),
        page: int = Query(1, ge=1),
        size: int = Query(50, ge=1, le=100),
        db: Session = Depends(get_db)
):
    """Get all penjualan with filtering and pagination"""

    query = db.query(Penjualan).options(
        selectinload(Penjualan.penjualan_items),
        selectinload(Penjualan.attachments),
        selectinload(Penjualan.customer_rel),  # Changed: vendor relationship
        selectinload(Penjualan.warehouse_rel)
    ).filter(Penjualan.is_deleted == False)

    # Apply filters
    if status_penjualan is not None and status_penjualan != StatusPembelianEnum.ALL:
        query = query.filter(Penjualan.status_penjualan == status_penjualan)
    if status_pembayaran is not None and status_pembayaran != StatusPembayaranEnum.ALL:
        query = query.filter(Penjualan.status_pembayaran == status_pembayaran)
    if customer_id:  # Changed: customer_id filter
        query = query.filter(Penjualan.customer_id == customer_id)
    if warehouse_id:
        query = query.filter(Penjualan.warehouse_id == warehouse_id)

    # Apply pagination
    offset = (page - 1) * size
    penjualans = query.order_by(desc(Penjualan.sales_date)).offset(offset).limit(size).all()

    result = []
    for penjualan in penjualans:
        customer_name = penjualan.customer_name
        if not customer_name and penjualan.customer_rel:
            customer_name = penjualan.customer_rel.name

        warehouse_name = penjualan.warehouse_name
        if not warehouse_name and penjualan.warehouse_rel:
            warehouse_name = penjualan.warehouse_rel.name

        penjualan_dict = {
            "id": penjualan.id,
            "no_penjualan": penjualan.no_penjualan,
            "status_pembayaran": penjualan.status_pembayaran,
            "status_penjualan": penjualan.status_penjualan,
            "sales_date": penjualan.sales_date,
            "total_paid": penjualan.total_paid.quantize(Decimal('0.0001')),
            "total_qty": penjualan.total_qty,
            "total_price": penjualan.total_price.quantize(Decimal('0.0001')),
            "customer_name": customer_name,  # Changed: customer_name instead of customer_name
            "warehouse_name": warehouse_name,
            "items_count": len(penjualan.penjualan_items),
            "attachments_count": len(penjualan.attachments)
        }
        result.append(PenjualanListResponse(**penjualan_dict))

    return {
        "data": result,
        "total": query.count(),
    }

@router.get("/{penjualan_id}", response_model=PenjualanResponse)
async def get_penjualan(penjualan_id: str, db: Session = Depends(get_db)):
    """Get specific penjualan by ID"""

    # Fixed: Added proper eager loading for all relationships
    penjualan = db.query(Penjualan).options(
        selectinload(Penjualan.penjualan_items).selectinload(PenjualanItem.item_rel),
        selectinload(Penjualan.attachments),
        selectinload(Penjualan.customer_rel), 
        selectinload(Penjualan.warehouse_rel),
        selectinload(Penjualan.top_rel)
    ).filter(Penjualan.id == penjualan_id).first()

    if not penjualan:
        raise HTTPException(status_code=404, detail="penjualan not found")

    return penjualan


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_penjualan(request: PenjualanCreate, db: Session = Depends(get_db)):
    """Create new penjualan in DRAFT status"""

    existing = db.query(Penjualan).filter(Penjualan.no_penjualan == request.no_penjualan).first()
    if existing:
        raise HTTPException(status_code=400, detail="No penjualan sudah ada")

    validate_penjualan_items_stock(db, request.items)

    new_penjualan = Penjualan(
        id=generate_penjualan_id(),
        no_penjualan = generate_unique_record_number(db, Penjualan, prefix="QP/SI"),
        warehouse_id=request.warehouse_id,
        customer_id=request.customer_id,
        top_id=request.top_id,
        sales_date=request.sales_date,
        sales_due_date=request.sales_due_date,
        discount=request.discount,
        additional_discount=request.additional_discount,
        expense=request.expense,
        status_penjualan=StatusPembelianEnum.DRAFT
    )

    db.add(new_penjualan)
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

        penjualan_item = PenjualanItem(
            penjualan_id=new_penjualan.id,
            item_id=item_request.item_id,
            item_name=item.name,
            qty=item_request.qty,
            unit_price=unit_price,  # ← USE USER INPUT!
            tax_percentage=item_request.tax_percentage,
            total_price=total_price
        )
        db.add(penjualan_item)

    db.commit()

    # Calculate totals
    calculate_penjualan_totals(db, new_penjualan.id)

    return {
        "detail": "penjualan created successfully",
        "id": new_penjualan.id,
    }

@router.put("/{penjualan_id}", response_model=PenjualanResponse)
async def update_penjualan(
    penjualan_id: int,
    request: PenjualanUpdate,
    db: Session = Depends(get_db),
):
    penjualan = db.query(Penjualan).filter(Penjualan.id == penjualan_id).first()
    if not penjualan:
        raise HTTPException(status_code=404, detail="penjualan not found")
    validate_draft_status(penjualan)


    update_data = request.dict(exclude_unset=True)
    items_data = update_data.pop("items", None)
    for field, value in update_data.items():
        setattr(penjualan, field, value)

    if items_data is not None:
        validate_penjualan_items_stock(db, items_data)

        db.query(PenjualanItem).filter(
            PenjualanItem.penjualan_id == penjualan_id
        ).delete()

        for item_req in items_data:
            item = db.query(Item).filter(Item.id == item_req["item_id"]).first()
            if not item:
                raise HTTPException(
                    status_code=404,
                    detail=f"Item with ID {item_req['item_id']} not found",
                )

            unit_price = Decimal(str(item_req["unit_price"]))
            qty = int(item_req["qty"])
            tax_percentage = int(item_req.get("tax_percentage", 0))

            total_price = calculate_item_total(qty, unit_price)

            db.add(PenjualanItem(
                penjualan_id=penjualan_id,
                item_id=item.id,
                item_name=item.name,
                qty=qty,
                unit_price=unit_price,        
                total_price=total_price,
                tax_percentage=tax_percentage,
            ))

    db.commit()
    calculate_penjualan_totals(db, penjualan_id)
    db.commit()

    return await get_penjualan(penjualan_id, db)

@router.post("/{penjualan_id}/finalize", response_model=PenjualanResponse)
async def finalize_penjualan_endpoint(penjualan_id: int, db: Session = Depends(get_db)):

    finalize_penjualan(db, penjualan_id)
    return await get_penjualan(penjualan_id, db)

@router.put("/{penjualan_id}/status", response_model=PenjualanResponse)
async def update_status(
        penjualan_id: str,
        request: PenjualanStatusUpdate,
        db: Session = Depends(get_db)
):
    """Update penjualan status"""

    penjualan = db.query(Penjualan).filter(Penjualan.id == penjualan_id).first()
    if not penjualan:
        raise HTTPException(status_code=404, detail="penjualan not found")

    if request.status_penjualan:
        penjualan.status_penjualan = request.status_penjualan
    if request.status_pembayaran:
        penjualan.status_pembayaran = request.status_pembayaran

    db.commit()
    return await get_penjualan(penjualan_id, db)



@router.patch("/{penjualan_id}", status_code=status.HTTP_200_OK)
async def rollback_penjualan_status(penjualan_id: int, db: Session = Depends(get_db)):
    """
    Rolls back the status of a purchase ('Pembelian') to 'DRAFT'
    if its current status is 'ACTIVE' or 'COMPLETED'.
    
    Args:
        pembelian_id: The unique ID of the purchase to update.
        db: The database session dependency.
    """

    query = db.query(Penjualan).filter(Penjualan.id == penjualan_id)
    

    penjualan = query.first()


    if not penjualan:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Penjualan not found")


    if penjualan.status_penjualan in (StatusPembelianEnum.ACTIVE, StatusPembelianEnum.COMPLETED):
        penjualan.status_penjualan = StatusPembelianEnum.DRAFT
    
    db.commit()
    db.refresh(penjualan)
    return {
        "msg": "Penjualan status changed successfully"
    }

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
            selectinload(Penjualan.pembayaran_rel),   # load payments to decide path
        )
        .filter(Penjualan.id == penjualan_id)
        .first()
    )

    if not penjualan:
        raise HTTPException(status_code=404, detail="Penjualan not found")

    # If you already enforce DRAFT-only deletion, keep this. Otherwise, remove and rely on the branching below.
    # This will raise if not DRAFT.
    validate_draft_status(penjualan)

    has_payments = bool(penjualan.pembayaran_rel)

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

# Statistics endpoints
@router.get("/stats/summary")
async def get_penjualan_summary(db: Session = Depends(get_db)):
    """Get penjualan statistics summary"""

    total_count = db.query(func.count(Penjualan.id)).scalar()
    draft_count = db.query(func.count(Penjualan.id)).filter(
        Penjualan.status_penjualan == StatusPembelianEnum.DRAFT
    ).scalar()
    active_count = db.query(func.count(Penjualan.id)).filter(
        Penjualan.status_penjualan == StatusPembelianEnum.ACTIVE
    ).scalar()
    completed_count = db.query(func.count(Penjualan.id)).filter(
        Penjualan.status_penjualan == StatusPembelianEnum.COMPLETED
    ).scalar()

    total_value = db.query(func.sum(Penjualan.total_price)).scalar() or 0
    unpaid_value = db.query(func.sum(Penjualan.total_price)).filter(
        Penjualan.status_pembayaran == StatusPembayaranEnum.UNPAID
    ).scalar() or 0

    return {
        "total_penjualan": total_count,
        "draft_count": draft_count,
        "active_count": active_count,
        "completed_count": completed_count,
        "total_value": total_value,
        "unpaid_value": unpaid_value
    }



@router.get("/{penjualan_id}/invoice/html", response_class=HTMLResponse)
async def view_penjualan_invoice_html(penjualan_id: int, request: Request, db: Session = Depends(get_db)):
    penjualan = (
        db.query(Penjualan)
        .options(
            joinedload(Penjualan.penjualan_items)
            .joinedload(PenjualanItem.item_rel)
            .joinedload(Item.attachments)
        )
        .filter(Penjualan.id == penjualan_id)
        .first()
    )
    if not penjualan:
        raise HTTPException(status_code=404, detail="Penjualan not found")

    BASE_URL = os.getenv("BASE_URL", "https://qiu-system.qiuparts.com")

    enhanced_items = []
    for it in penjualan.penjualan_items:
        raw = it.item_rel.primary_image_url if it.item_rel else None
        img_url = to_public_image_url(raw, request, BASE_URL)
        enhanced_items.append({
            "item": it,
            "image_url": img_url,
            "item_name": it.item_name,
            "qty": it.qty,
            "satuan_name": it.satuan_name,
            "tax_percentage": it.tax_percentage,
            "unit_price": it.unit_price,
            "total_price": it.total_price,
        })

    subtotal = Decimal(0)
    tax_amount = Decimal(0)
    for item in penjualan.penjualan_items:
        item_total = Decimal(str(item.total_price or 0))
        subtotal += item_total
        if item.tax_percentage:
            item_tax = item_total * Decimal(str(item.tax_percentage)) / Decimal('100')
            tax_amount += item_tax

    discount = Decimal(str(penjualan.discount or 0))
    additional_discount = Decimal(str(penjualan.additional_discount or 0))
    final_total = subtotal - discount - additional_discount
    expense = Decimal(str(penjualan.expense or 0))
    grand_total = final_total + tax_amount + expense

    totals = {
        "subtotal": subtotal,
        "tax_amount": tax_amount,
        "final_total": final_total,
        "grand_total": grand_total,
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