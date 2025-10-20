from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func, cast, Integer
from typing import List, Optional
from datetime import datetime, time, date
from decimal import Decimal

from database import get_db
from models.AuditTrail import AuditEntityEnum
from models.Pengembalian import Pengembalian, PengembalianItem
from models.Pembelian import Pembelian, StatusPembayaranEnum, StatusPembelianEnum
from models.Penjualan import Penjualan
from models.Item import Item
from routes.pembayaran_routes import update_payment_status
from schemas.PembayaranSchemas import PembayaranPengembalianType
from schemas.PengembalianSchema import (
    PengembalianCreate, PengembalianUpdate, PengembalianResponse,
    PengembalianListResponse, PengembalianItemResponse
)
from services.audit_services import AuditService
from utils import generate_unique_record_number, get_current_user_name

router = APIRouter()


def calculate_item_totals(item: PengembalianItem) -> None:
    """
    Calculate line totals for return items (NO discount):
      sub_total = qty * unit_price
      line_tax = sub_total * (tax% / 100)
      total_return = sub_total + line_tax
    """
    qty = Decimal(str(item.qty_returned or 0))
    unit_price = Decimal(str(item.unit_price or 0))
    tax_percentage = Decimal(str(item.tax_percentage or 0))

    sub_total = qty * unit_price
    line_tax = (sub_total * tax_percentage) / Decimal('100')
    total_return = sub_total + line_tax

    item.sub_total = sub_total
    item.total_return = total_return


def calculate_pengembalian_totals(pengembalian: Pengembalian) -> None:
    """
    Calculate totals from items (NO discounts):
      total_subtotal = sum of all item sub_totals
      total_tax = sum of all item taxes
      total_return = total_subtotal + total_tax
    """
    total_subtotal = Decimal("0.00")
    total_tax = Decimal("0.00")
    
    for item in pengembalian.pengembalian_items:
        calculate_item_totals(item)
        
        qty = Decimal(str(item.qty_returned or 0))
        unit = Decimal(str(item.unit_price or 0))
        tax_pct = Decimal(str(item.tax_percentage or 0))
        
        sub_total = qty * unit
        line_tax = (sub_total * tax_pct) / Decimal('100')
        
        total_subtotal += sub_total
        total_tax += line_tax
    
    total_return = total_subtotal + total_tax
    
    pengembalian.total_subtotal = total_subtotal
    pengembalian.total_tax = total_tax
    pengembalian.total_return = total_return


def recalc_return_and_update_payment_status(
    db: Session, 
    reference_id: int, 
    reference_type: PembayaranPengembalianType, 
    no_pengembalian: str, 
    user_name: str
) -> None:
    """
    1) Recalculate and persist total_return on the referenced record (Pembelian/Penjualan)
       from ACTIVE pengembalian rows.
    2) Delegate to update_payment_status to set payment statuses.
    """
    if reference_type == PembayaranPengembalianType.PEMBELIAN:
        record = db.query(Pembelian).filter(Pembelian.id == reference_id).first()
        filter_condition = (Pengembalian.pembelian_id == reference_id)
    else:
        record = db.query(Penjualan).filter(Penjualan.id == reference_id).first()
        filter_condition = (Pengembalian.penjualan_id == reference_id)

    if not record:
        return

    # Sum all active returns for this reference
    total_returns = (
        db.query(func.coalesce(func.sum(Pengembalian.total_return), 0))
          .filter(Pengembalian.status == StatusPembelianEnum.ACTIVE)
          .filter(filter_condition)
          .scalar()
        or Decimal("0.00")
    )

    # Update the reference record's total_return
    record.total_return = Decimal(str(total_returns))
    db.flush()

    # Update payment status using the shared function
    update_payment_status(db, reference_id, reference_type, user_name, no_pengembalian, "Pengembalian")


# Validation helpers
def _normalize_item_payload(obj):
    """Normalize item data from dict or object"""
    if isinstance(obj, dict):
        data = obj
    else:
        data = obj.dict() if hasattr(obj, "dict") else obj.model_dump()

    try:
        qty_returned = int(data.get("qty_returned", 0))
        unit_price = Decimal(str(data.get("unit_price", "0")))
        tax_percentage = int(data.get("tax_percentage", 0) or 0)
    except (ValueError, Exception):
        raise HTTPException(status_code=400, detail="Invalid numeric values in items")

    return {
        "item_id": data.get("item_id"),
        "qty_returned": qty_returned,
        "unit_price": unit_price,
        "tax_percentage": tax_percentage,
    }


def _validate_items_payload(items_data: List):
    """Validate items payload"""
    seen = set()
    for idx, raw in enumerate(items_data or []):
        item_id = raw.get("item_id") if isinstance(raw, dict) else getattr(raw, "item_id", None)
        if not item_id:
            raise HTTPException(status_code=400, detail=f"items[{idx}]: item_id is required")

        if item_id in seen:
            raise HTTPException(status_code=400, detail=f"Duplicate item_id in payload: {item_id}")
        seen.add(item_id)

        d = _normalize_item_payload(raw)
        if d["qty_returned"] < 1:
            raise HTTPException(status_code=400, detail=f"items[{idx}]: qty_returned must be >= 1")
        if d["unit_price"] < 0:
            raise HTTPException(status_code=400, detail=f"items[{idx}]: unit_price must be >= 0")
        if not (0 <= d["tax_percentage"] <= 100):
            raise HTTPException(status_code=400, detail=f"items[{idx}]: tax_percentage must be between 0 and 100")


@router.post("", response_model=PengembalianResponse)
def create_pengembalian(
    pengembalian_data: PengembalianCreate, 
    db: Session = Depends(get_db), 
    user_name: str = Depends(get_current_user_name)
):
    """Create a new return record (DRAFT)"""
    audit_service = AuditService(db)

    # Validate items exist
    if not pengembalian_data.pengembalian_items or len(pengembalian_data.pengembalian_items) == 0:
        raise HTTPException(status_code=400, detail="Return items are required")

    _validate_items_payload([item.model_dump() for item in pengembalian_data.pengembalian_items])

    # Validate reference exists and is active
    if pengembalian_data.reference_type == PembayaranPengembalianType.PEMBELIAN:
        pengembalian_data.penjualan_id = None
        pengembalian_data.customer_id = None
        pembelian = db.query(Pembelian).filter(
            Pembelian.id == pengembalian_data.pembelian_id,
            Pembelian.is_deleted == False,
            Pembelian.status_pembelian.in_([StatusPembelianEnum.ACTIVE, StatusPembelianEnum.PROCESSED])
        ).first()
        if not pembelian:
            raise HTTPException(
                status_code=404, 
                detail=f"Active Pembelian with ID {pengembalian_data.pembelian_id} not found"
            )
    else:
        pengembalian_data.pembelian_id = None
        pengembalian_data.vendor_id = None
        penjualan = db.query(Penjualan).filter(
            Penjualan.id == pengembalian_data.penjualan_id,
            Penjualan.is_deleted == False,
            Penjualan.status_penjualan.in_([StatusPembelianEnum.ACTIVE, StatusPembelianEnum.PROCESSED])
        ).first()
        if not penjualan:
            raise HTTPException(
                status_code=404, 
                detail=f"Active Penjualan with ID {pengembalian_data.penjualan_id} not found"
            )

    # Validate all items exist
    for item_data in pengembalian_data.pengembalian_items:
        item = db.query(Item).filter(Item.id == item_data.item_id).first()
        if not item:
            raise HTTPException(status_code=404, detail=f"Item with ID {item_data.item_id} not found")

    # Create pengembalian record
    pengembalian_dict = pengembalian_data.model_dump(exclude={'pengembalian_items'})
    pengembalian = Pengembalian(**pengembalian_dict)

    # Generate unique return number
    pengembalian.no_pengembalian = generate_unique_record_number(db, Pengembalian, "QP/RET")
    pengembalian.created_at = datetime.now()
    pengembalian.status = StatusPembelianEnum.DRAFT
    pengembalian.total_return = Decimal("0.00")

    db.add(pengembalian)
    db.flush()

    # Create return items
    for item_data in pengembalian_data.pengembalian_items:
        item = db.query(Item).filter(Item.id == item_data.item_id).first()
        
        pengembalian_item = PengembalianItem(
            pengembalian_id=pengembalian.id,
            item_id=item_data.item_id,
            item_code=item.code if item else None,
            item_name=item.name if item else None,
            qty_returned=item_data.qty_returned,
            unit_price=item_data.unit_price,
            tax_percentage=item_data.tax_percentage or 0
        )
        db.add(pengembalian_item)

    db.flush()
    
    # Calculate totals
    calculate_pengembalian_totals(pengembalian)

    audit_service.default_log(
        entity_id=pengembalian.id,
        entity_type=AuditEntityEnum.PENGEMBALIAN,
        description=f"Pengembalian {pengembalian.no_pengembalian} dibuat, total: Rp{pengembalian.total_return}",
        user_name=user_name
    )

    db.commit()
    db.refresh(pengembalian)

    return {"msg": "Pengembalian berhasil dibuat"}


@router.get("", response_model=PengembalianListResponse)
def get_pengembalians(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    reference_type: Optional[PembayaranPengembalianType] = None,
    status: Optional[StatusPembelianEnum] = None,
    search_key: Optional[str] = Query(None, description="Search by return number"),
    to_date: Optional[date] = Query(None, description="Filter by date"),
    from_date: Optional[date] = Query(None, description="Filter by date"),
    db: Session = Depends(get_db)
):
    """Get list of return records with filtering"""
    query = db.query(Pengembalian).filter().order_by(
        cast(func.substr(Pengembalian.no_pengembalian,
                         func.length(Pengembalian.no_pengembalian) - 3), Integer).desc(),
        cast(func.substr(Pengembalian.no_pengembalian,
                         func.length(Pengembalian.no_pengembalian) - 6, 2), Integer).desc(),
        cast(func.substr(Pengembalian.no_pengembalian, 7, 4), Integer).desc()
    )

    # Date filters
    if from_date and to_date:
        query = query.filter(
            Pengembalian.created_at.between(
                datetime.combine(from_date, time.min),
                datetime.combine(to_date, time.max),
            )
        )
    elif from_date:
        query = query.filter(Pengembalian.created_at >= datetime.combine(from_date, time.min))
    elif to_date:
        query = query.filter(Pengembalian.created_at <= datetime.combine(to_date, time.max))

    # Type and status filters
    if reference_type and reference_type != "ALL":
        query = query.filter(Pengembalian.reference_type == reference_type)

    if status and status != "ALL":
        query = query.filter(Pengembalian.status == status)
        
    if search_key:
        query = query.filter(Pengembalian.no_pengembalian.ilike(f"%{search_key}%"))

    total = query.count()

    pengembalians = query.options(
        joinedload(Pengembalian.pengembalian_items).joinedload(PengembalianItem.item_rel),
        joinedload(Pengembalian.pembelian_rel),
        joinedload(Pengembalian.penjualan_rel),
        joinedload(Pengembalian.customer_rel),
        joinedload(Pengembalian.vend_rel),
        joinedload(Pengembalian.warehouse_rel),
        joinedload(Pengembalian.curr_rel)
    ).order_by(Pengembalian.created_at.desc()).offset(skip).limit(limit).all()

    return PengembalianListResponse(
        data=pengembalians,
        total=total,
        skip=skip,
        limit=limit
    )


@router.get("/{pengembalian_id}", response_model=PengembalianResponse)
def get_pengembalian(pengembalian_id: int, db: Session = Depends(get_db)):
    """Get return record by ID"""
    pengembalian = db.query(Pengembalian).options(
        joinedload(Pengembalian.pengembalian_items).joinedload(PengembalianItem.item_rel),
        joinedload(Pengembalian.pembelian_rel),
        joinedload(Pengembalian.penjualan_rel),
        joinedload(Pengembalian.customer_rel),
        joinedload(Pengembalian.vend_rel),
        joinedload(Pengembalian.warehouse_rel),
        joinedload(Pengembalian.curr_rel)
    ).filter(Pengembalian.id == pengembalian_id).first()
    if not pengembalian:
        raise HTTPException(status_code=404, detail="Pengembalian not found")

    return pengembalian


@router.put("/{pengembalian_id}/finalize")
def finalize_pengembalian(
    pengembalian_id: int,
    db: Session = Depends(get_db),
    user_name: str = Depends(get_current_user_name)
):
    """Finalize a DRAFT pengembalian -> ACTIVE, then update reference payment status."""
    audit_service = AuditService(db)

    pengembalian = db.query(Pengembalian).filter(Pengembalian.id == pengembalian_id).first()
    if not pengembalian:
        raise HTTPException(status_code=404, detail="Pengembalian not found")

    if pengembalian.status == StatusPembelianEnum.ACTIVE:
        raise HTTPException(status_code=400, detail="Pengembalian already finalized")

    if pengembalian.status != StatusPembelianEnum.DRAFT:
        raise HTTPException(status_code=400, detail="Only draft returns can be finalized")

    # make sure totals are up-to-date before finalizing
    calculate_pengembalian_totals(pengembalian)
    db.flush()

    pengembalian.status = StatusPembelianEnum.ACTIVE
    db.flush()

    # Update reference payment/return aggregates
    if pengembalian.reference_type == PembayaranPengembalianType.PEMBELIAN and pengembalian.pembelian_id:
        recalc_return_and_update_payment_status(
            db, pengembalian.pembelian_id,
            PembayaranPengembalianType.PEMBELIAN,
            pengembalian.no_pengembalian,
            user_name
        )
    elif pengembalian.reference_type == PembayaranPengembalianType.PENJUALAN and pengembalian.penjualan_id:
        recalc_return_and_update_payment_status(
            db, pengembalian.penjualan_id,
            PembayaranPengembalianType.PENJUALAN,
            pengembalian.no_pengembalian,
            user_name
        )

    audit_service.default_log(
        entity_id=pengembalian.id,
        entity_type=AuditEntityEnum.PENGEMBALIAN,
        description=f"Pengembalian {pengembalian.no_pengembalian} difinalisasi, total: Rp{pengembalian.total_return}",
        user_name=user_name
    )

    db.commit()
    db.refresh(pengembalian)
    return {"message": "Pengembalian finalized successfully", "pengembalian": pengembalian}


@router.put("/{pengembalian_id}", response_model=PengembalianResponse)
def update_pengembalian(
    pengembalian_id: int,
    pengembalian_data: PengembalianUpdate,
    db: Session = Depends(get_db),
    user_name: str = Depends(get_current_user_name)
):
    """
    Update a pengembalian (only allowed in DRAFT).
    If items are provided, replace all items and recalc totals (with tax).
    """
    audit_service = AuditService(db)

    pengembalian = db.query(Pengembalian).filter(Pengembalian.id == pengembalian_id).first()
    if not pengembalian:
        raise HTTPException(status_code=404, detail="Pengembalian not found")

    if pengembalian.status != StatusPembelianEnum.DRAFT:
        raise HTTPException(status_code=400, detail="Only draft returns can be updated")

    # Update scalar fields
    main_updates = pengembalian_data.model_dump(exclude={"pengembalian_items"}, exclude_unset=True)
    for field, value in main_updates.items():
        setattr(pengembalian, field, value)

    # Replace items if provided
    if pengembalian_data.pengembalian_items is not None:
        # Validate payload first (duplicates, ranges, etc.)
        _validate_items_payload([it.model_dump() for it in pengembalian_data.pengembalian_items])

        # Ensure all items exist
        item_ids = [it.item_id for it in pengembalian_data.pengembalian_items]
        found_count = db.query(Item.id).filter(Item.id.in_(item_ids)).count()
        if found_count != len(item_ids):
            raise HTTPException(status_code=404, detail="One or more items not found")

        # Delete existing
        for it in list(pengembalian.pengembalian_items):
            db.delete(it)
        db.flush()

        # Create new items (snapshot fields + tax)
        for it in pengembalian_data.pengembalian_items:
            item_obj = db.query(Item).filter(Item.id == it.item_id).first()
            new_item = PengembalianItem(
                pengembalian_id=pengembalian.id,
                item_id=it.item_id,
                item_code=item_obj.code if item_obj else None,
                item_name=item_obj.name if item_obj else None,
                qty_returned=it.qty_returned,
                unit_price=it.unit_price,
                tax_percentage=it.tax_percentage or 0,
            )
            # compute per-line totals
            calculate_item_totals(new_item)
            db.add(new_item)

        db.flush()
        # Recompute header totals
        calculate_pengembalian_totals(pengembalian)

    audit_service.default_log(
        entity_id=pengembalian.id,
        entity_type=AuditEntityEnum.PENGEMBALIAN,
        description=f"Pengembalian {pengembalian.no_pengembalian} diperbarui, total: Rp{pengembalian.total_return}",
        user_name=user_name
    )

    db.commit()
    db.refresh(pengembalian)
    return pengembalian


@router.delete("/{pengembalian_id}")
def delete_pengembalian(
    pengembalian_id: int,
    db: Session = Depends(get_db),
    user_name: str = Depends(get_current_user_name)
):
    """
    Delete a pengembalian by ID.
    Will also recalc reference payment status after delete (ACTIVE pengembalian
    of the same reference still count).
    """
    audit_service = AuditService(db)

    pengembalian = db.query(Pengembalian).filter(Pengembalian.id == pengembalian_id).first()
    if not pengembalian:
        raise HTTPException(status_code=404, detail="Pengembalian not found")

    try:
        pembelian_id = pengembalian.pembelian_id
        penjualan_id = pengembalian.penjualan_id
        ref_type = pengembalian.reference_type
        nomor = pengembalian.no_pengembalian

        db.delete(pengembalian)
        db.commit()

        # Recalc/Update reference payment status after deletion
        if ref_type == PembayaranPengembalianType.PEMBELIAN and pembelian_id:
            recalc_return_and_update_payment_status(
                db, pembelian_id, PembayaranPengembalianType.PEMBELIAN, nomor, user_name
            )
        elif ref_type == PembayaranPengembalianType.PENJUALAN and penjualan_id:
            recalc_return_and_update_payment_status(
                db, penjualan_id, PembayaranPengembalianType.PENJUALAN, nomor, user_name
            )

        audit_service.default_log(
            entity_id=pengembalian_id,
            entity_type=AuditEntityEnum.PENGEMBALIAN,
            description=f"Pengembalian {nomor} dihapus",
            user_name=user_name
        )

        db.commit()
        return {"message": "Pengembalian deleted successfully"}

    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error deleting pengembalian: {str(e)}")


@router.get("/{pengembalian_id}/items", response_model=List[PengembalianItemResponse])
def get_pengembalian_items(
    pengembalian_id: int,
    db: Session = Depends(get_db)
):
    """List items of a pengembalian."""
    parent = db.query(Pengembalian).filter(Pengembalian.id == pengembalian_id).first()
    if not parent:
        raise HTTPException(status_code=404, detail="Pengembalian not found")

    items = (
        db.query(PengembalianItem)
        .options(joinedload(PengembalianItem.item_rel))
        .filter(PengembalianItem.pengembalian_id == pengembalian_id)
        .all()
    )
    return items


@router.put("/{pengembalian_id}/draft")
def revert_to_draft(
    pengembalian_id: int,
    db: Session = Depends(get_db),
    user_name: str = Depends(get_current_user_name)
):
    """
    Revert an ACTIVE pengembalian back to DRAFT.
    This will recalc the reference's total_return and payment status accordingly.
    """
    audit_service = AuditService(db)

    pengembalian = db.query(Pengembalian).filter(Pengembalian.id == pengembalian_id).first()
    if not pengembalian:
        raise HTTPException(status_code=404, detail="Pengembalian not found")

    if pengembalian.status != StatusPembelianEnum.ACTIVE:
        raise HTTPException(status_code=400, detail="Only active returns can be reverted to draft")

    pengembalian.status = StatusPembelianEnum.DRAFT
    db.flush()

    # Recalc reference payment status after removing this from ACTIVE pool
    if pengembalian.reference_type == PembayaranPengembalianType.PEMBELIAN and pengembalian.pembelian_id:
        recalc_return_and_update_payment_status(
            db, pengembalian.pembelian_id,
            PembayaranPengembalianType.PEMBELIAN,
            pengembalian.no_pengembalian,
            user_name
        )
    elif pengembalian.reference_type == PembayaranPengembalianType.PENJUALAN and pengembalian.penjualan_id:
        recalc_return_and_update_payment_status(
            db, pengembalian.penjualan_id,
            PembayaranPengembalianType.PENJUALAN,
            pengembalian.no_pengembalian,
            user_name
        )

    audit_service.default_log(
        entity_id=pengembalian.id,
        entity_type=AuditEntityEnum.PENGEMBALIAN,
        description=f"Pengembalian {pengembalian.no_pengembalian} dikembalikan ke DRAFT",
        user_name=user_name
    )

    db.commit()
    db.refresh(pengembalian)
    return {"message": "Pengembalian reverted to draft successfully", "pengembalian": pengembalian}
