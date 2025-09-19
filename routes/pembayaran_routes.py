from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import or_, and_, func, cast, Integer
from typing import List, Optional
from datetime import datetime, date, time
from decimal import Decimal

from database import get_db
from models.Pembayaran import Pembayaran, PembayaranDetails, PembayaranPengembalianType
from models.Pembelian import Pembelian, StatusPembayaranEnum, StatusPembelianEnum
from models.Penjualan import Penjualan
from schemas.PembayaranSchemas import (
    PembayaranCreate, PembayaranUpdate, PembayaranResponse,
    PembayaranListResponse, PembayaranFilter, PembayaranDetailResponse
)
from utils import soft_delete_record, generate_unique_record_number

router = APIRouter()

# Helper function to update payment status
def update_payment_status(db: Session, reference_id: int, reference_type: PembayaranPengembalianType):
    if reference_type == PembayaranPengembalianType.PEMBELIAN:
        record = db.query(Pembelian).filter(Pembelian.id == reference_id).first()
    else:
        record = db.query(Penjualan).filter(Penjualan.id == reference_id).first()

    if not record:
        return

    filters = [Pembayaran.status == StatusPembelianEnum.ACTIVE]
    if reference_type == PembayaranPengembalianType.PEMBELIAN:
        filters.append(PembayaranDetails.pembelian_id == reference_id)
    else:
        filters.append(PembayaranDetails.penjualan_id == reference_id)

    total_payments = db.query(func.sum(PembayaranDetails.total_paid)) \
                         .join(Pembayaran, PembayaranDetails.pembayaran_id == Pembayaran.id) \
                         .filter(*filters) \
                         .scalar() or Decimal("0.00")

    record.total_paid = total_payments

    total_return = record.total_return or Decimal("0.00")
    total_outstanding = record.total_price - (record.total_paid + total_return)

    # Update status pembayaran
    if total_outstanding <= 0:
        record.status_pembayaran = StatusPembayaranEnum.PAID
        if reference_type == PembayaranPengembalianType.PEMBELIAN:
            record.status_pembelian = StatusPembelianEnum.COMPLETED
        else:
            record.status_penjualan = StatusPembelianEnum.COMPLETED
    elif record.total_paid > 0 or record.total_return > 0:
        record.status_pembayaran = StatusPembayaranEnum.HALF_PAID
        if reference_type == PembayaranPengembalianType.PEMBELIAN:
            record.status_pembelian = StatusPembelianEnum.PROCESSED
        else:
            record.status_penjualan = StatusPembelianEnum.PROCESSED
    else:
        record.status_pembayaran = StatusPembayaranEnum.UNPAID


@router.post("", response_model=PembayaranResponse)
def create_pembayaran(pembayaran_data: PembayaranCreate, db: Session = Depends(get_db)):
    """Create a new payment record"""

    # Validate payment details exist
    if not pembayaran_data.pembayaran_details or len(pembayaran_data.pembayaran_details) == 0:
        raise HTTPException(status_code=400, detail="Payment details are required")

    # Validate reference type consistency and check if records exist
    for detail in pembayaran_data.pembayaran_details:
        if pembayaran_data.reference_type == PembayaranPengembalianType.PEMBELIAN:
            if not detail.pembelian_id:
                raise HTTPException(status_code=400, detail="pembelian_id is required for PEMBELIAN type")

            pembelian = db.query(Pembelian).filter(
                Pembelian.id == detail.pembelian_id,
                Pembelian.is_deleted == False,
                Pembelian.status_pembelian.in_([StatusPembelianEnum.ACTIVE, StatusPembelianEnum.PROCESSED])
            ).first()
            if not pembelian:
                raise HTTPException(status_code=404, detail=f"Active Pembelian with ID {detail.pembelian_id} not found")

        else:  # PENJUALAN
            if not detail.penjualan_id:
                raise HTTPException(status_code=400, detail="penjualan_id is required for PENJUALAN type")

            penjualan = db.query(Penjualan).filter(
                Penjualan.id == detail.penjualan_id,
                Penjualan.is_deleted == False,
                Penjualan.status_penjualan.in_([StatusPembelianEnum.ACTIVE, StatusPembelianEnum.PROCESSED])
            ).first()
            if not penjualan:
                raise HTTPException(status_code=404, detail=f"Active Penjualan with ID {detail.penjualan_id} not found")

    # Create payment record - EXCLUDE total_paid from pembayaran_dict
    pembayaran_dict = pembayaran_data.model_dump(exclude={'pembayaran_details'})
    # Remove total_paid if it exists since it doesn't belong in Pembayaran model
    pembayaran_dict.pop('total_paid', None)

    pembayaran = Pembayaran(**pembayaran_dict)

    # Generate unique payment number based on type
    if pembayaran_data.reference_type == PembayaranPengembalianType.PEMBELIAN:
        pembayaran.no_pembayaran = generate_unique_record_number(db, Pembayaran, "QP/AR")
    else:
        pembayaran.no_pembayaran = generate_unique_record_number(db, Pembayaran, "QP/AP")

    pembayaran.created_at = datetime.now()
    pembayaran.status = StatusPembelianEnum.DRAFT

    db.add(pembayaran)
    db.flush()

    # Create payment details
    for detail_data in pembayaran_data.pembayaran_details:
        detail = PembayaranDetails(
            pembayaran_id=pembayaran.id,
            **detail_data.model_dump()
        )
        db.add(detail)

    db.commit()
    db.refresh(pembayaran)

    return pembayaran

@router.get("", response_model=PembayaranListResponse)
def get_pembayarans(
        skip: int = Query(0, ge=0),
        limit: int = Query(100, ge=1, le=1000),
        reference_type: Optional[PembayaranPengembalianType] = None,
        status: Optional[StatusPembelianEnum] = None,
        db: Session = Depends(get_db),

        to_date : Optional[date] = Query(None, description="Filter by date"),
        from_date : Optional[date] = Query(None, description="Filter by date"),
):
    """Get list of payment records with filtering"""

    query = db.query(Pembayaran).filter().order_by(
        cast(func.substr(Pembayaran.no_pembayaran,
                         func.length(Pembayaran.no_pembayaran) - 3), Integer).desc(),

        cast(func.substr(Pembayaran.no_pembayaran,
                         func.length(Pembayaran.no_pembayaran) - 6, 2), Integer).desc(),
        # Extract sequence number (third part)
        cast(func.substr(Pembayaran.no_pembayaran, 7, 4), Integer).desc()
    )

    if reference_type and reference_type != "ALL":
        query = query.filter(Pembayaran.reference_type == reference_type)


    if from_date and to_date:
        query = query.filter(
            Pembayaran.created_at.between(
                datetime.combine(from_date, time.min),
                datetime.combine(to_date, time.max),
            )
        )
    elif from_date:
        query = query.filter(Pembayaran.created_at >= datetime.combine(from_date, time.min))
    elif to_date:
        query = query.filter(Pembayaran.created_at <= datetime.combine(to_date, time.max))

    if status and status != "ALL":
        query = query.filter(Pembayaran.status == status)

    total = query.count()

    # Get paginated results with relationships
    pembayarans = query.options(
        joinedload(Pembayaran.pembayaran_details).joinedload(PembayaranDetails.pembelian_rel),
        joinedload(Pembayaran.pembayaran_details).joinedload(PembayaranDetails.penjualan_rel),
        joinedload(Pembayaran.customer_rel),
        joinedload(Pembayaran.vend_rel),
        joinedload(Pembayaran.curr_rel)
    ).order_by(Pembayaran.created_at.desc()).offset(skip).limit(limit).all()

    return PembayaranListResponse(
        data=pembayarans,
        total=total,
        skip=skip,
        limit=limit
    )

@router.get("/{pembayaran_id}", response_model=PembayaranResponse)
def get_pembayaran(pembayaran_id: int, db: Session = Depends(get_db)):
    """Get payment record by ID"""

    pembayaran = db.query(Pembayaran).options(
        joinedload(Pembayaran.pembayaran_details).joinedload(PembayaranDetails.pembelian_rel),
        joinedload(Pembayaran.pembayaran_details).joinedload(PembayaranDetails.penjualan_rel),
        joinedload(Pembayaran.customer_rel),
        joinedload(Pembayaran.vend_rel),
        joinedload(Pembayaran.attachments),
        joinedload(Pembayaran.warehouse_rel),
        joinedload(Pembayaran.curr_rel)
    ).filter(
        Pembayaran.id == pembayaran_id,
        ).first()

    if not pembayaran:
        raise HTTPException(status_code=404, detail="Pembayaran not found")

    return pembayaran

@router.put("/{pembayaran_id}/finalize")
def finalize_pembayaran(pembayaran_id: int, db: Session = Depends(get_db)):
    """Finalize payment record by ID"""

    pembayaran = db.query(Pembayaran).filter(
        Pembayaran.id == pembayaran_id,
        ).first()

    if not pembayaran:
        raise HTTPException(status_code=404, detail="Pembayaran not found")

    if pembayaran.status == StatusPembelianEnum.ACTIVE:
        raise HTTPException(status_code=400, detail="Pembayaran already finalized")

    if pembayaran.status != StatusPembelianEnum.DRAFT:
        raise HTTPException(status_code=400, detail="Only draft payments can be finalized")

    pembayaran.status = StatusPembelianEnum.ACTIVE
    db.flush()

    for detail in pembayaran.pembayaran_details:
        if detail.pembelian_id:
            update_payment_status(db, detail.pembelian_id, PembayaranPengembalianType.PEMBELIAN)
        elif detail.penjualan_id:
            update_payment_status(db, detail.penjualan_id, PembayaranPengembalianType.PENJUALAN)

    db.commit()
    db.refresh(pembayaran)

    return {"message": "Pembayaran finalized successfully", "pembayaran": pembayaran}

@router.put("/{pembayaran_id}", response_model=PembayaranResponse)
def update_pembayaran(
        pembayaran_id: int,
        pembayaran_data: PembayaranUpdate,
        db: Session = Depends(get_db)
):
    """Update payment record"""

    pembayaran = db.query(Pembayaran).filter(
        Pembayaran.id == pembayaran_id,
        ).first()

    if not pembayaran:
        raise HTTPException(status_code=404, detail="Pembayaran not found")

    # Only allow updates if payment is in draft status
    if pembayaran.status != StatusPembelianEnum.DRAFT:
        raise HTTPException(status_code=400, detail="Only draft payments can be updated")

    # Store old reference info for status update
    old_details = [(detail.pembelian_id, detail.penjualan_id) for detail in pembayaran.pembayaran_details]
    old_reference_type = pembayaran.reference_type

    # Check if reference type is changing
    reference_type_changed = (
            pembayaran_data.reference_type is not None and
            pembayaran_data.reference_type != old_reference_type
    )

    # If reference type is changing, validate the new data consistency
    if reference_type_changed:
        new_reference_type = pembayaran_data.reference_type

        # Validate that customer_id/vendor_id matches the new reference type
        if new_reference_type == PembayaranPengembalianType.PENJUALAN:
            if pembayaran_data.customer_id is None and pembayaran.customer_id is None:
                raise HTTPException(
                    status_code=400,
                    detail="customer_id is required when reference_type is PENJUALAN"
                )
        else:  # PEMBELIAN
            if pembayaran_data.vendor_id is None and pembayaran.vendor_id is None:
                raise HTTPException(
                    status_code=400,
                    detail="vendor_id is required when reference_type is PEMBELIAN"
                )
          

        # Validate payment details consistency with new reference type
        if pembayaran_data.pembayaran_details:
            for detail in pembayaran_data.pembayaran_details:
                if new_reference_type == PembayaranPengembalianType.PENJUALAN:
                    if not detail.penjualan_id:
                        raise HTTPException(
                            status_code=400,
                            detail="penjualan_id is required in payment details when reference_type is PENJUALAN"
                        )
                   
                else:  # PEMBELIAN
                    if not detail.pembelian_id:
                        raise HTTPException(
                            status_code=400,
                            detail="pembelian_id is required in payment details when reference_type is PEMBELIAN"
                        )
                   

    # If reference type changed or payment details are provided, validate and check existence
    if pembayaran_data.pembayaran_details:
        current_reference_type = pembayaran_data.reference_type or pembayaran.reference_type

        for detail in pembayaran_data.pembayaran_details:
            if current_reference_type == PembayaranPengembalianType.PEMBELIAN:
                if detail.pembelian_id:
                    pembelian = db.query(Pembelian).filter(
                        Pembelian.id == detail.pembelian_id,
                        Pembelian.is_deleted == False,
                        Pembelian.status_pembelian.in_([StatusPembelianEnum.ACTIVE, StatusPembelianEnum.PROCESSED])
                    ).first()
                    if not pembelian:
                        raise HTTPException(
                            status_code=404,
                            detail=f"Active Pembelian with ID {detail.pembelian_id} not found"
                        )
            else:  # PENJUALAN
                if detail.penjualan_id:
                    penjualan = db.query(Penjualan).filter(
                        Penjualan.id == detail.penjualan_id,
                        Penjualan.is_deleted == False,
                        Penjualan.status_penjualan.in_([StatusPembelianEnum.ACTIVE, StatusPembelianEnum.PROCESSED])
                    ).first()
                    if not penjualan:
                        raise HTTPException(
                            status_code=404,
                            detail=f"Active Penjualan with ID {detail.penjualan_id} not found"
                        )

    # Update main pembayaran fields
    pembayaran_dict = pembayaran_data.model_dump(exclude={'pembayaran_details'}, exclude_unset=True)

    # If reference type is changing, clear the opposite ID field
    if reference_type_changed:
        if pembayaran_data.reference_type == PembayaranPengembalianType.PENJUALAN:
            pembayaran.vendor_id = None
        else:  # PEMBELIAN
            pembayaran.customer_id = None

    for field, value in pembayaran_dict.items():
        setattr(pembayaran, field, value)

    # Always delete and recreate payment details if provided or if reference type changed
    if pembayaran_data.pembayaran_details is not None or reference_type_changed:
        # Delete existing details
        for detail in pembayaran.pembayaran_details:
            db.delete(detail)
        db.flush()

        # Create new details (only if provided)
        if pembayaran_data.pembayaran_details:
            for detail_data in pembayaran_data.pembayaran_details:
                detail = PembayaranDetails(
                    pembayaran_id=pembayaran.id,
                    **detail_data.model_dump()
                )
                db.add(detail)

    db.commit()
    db.refresh(pembayaran)

    # Update payment status for old references
    for old_pembelian_id, old_penjualan_id in old_details:
        if old_pembelian_id:
            update_payment_status(db, old_pembelian_id, PembayaranPengembalianType.PEMBELIAN)
        elif old_penjualan_id:
            update_payment_status(db, old_penjualan_id, PembayaranPengembalianType.PENJUALAN)

    return pembayaran
@router.delete("/{pembayaran_id}")
def delete_pembayaran(pembayaran_id: int, db: Session = Depends(get_db)):
    """Delete payment record by ID"""
    pembayaran = db.query(Pembayaran).filter(
        Pembayaran.id == pembayaran_id,
        ).first()

    if not pembayaran:
        raise HTTPException(status_code=404, detail="Pembayaran not found")

    try:
        # Store reference info for status update
        processed_pembelian_ids = set()
        processed_penjualan_ids = set()

        for detail in pembayaran.pembayaran_details:
            if detail.pembelian_id:
                processed_pembelian_ids.add(detail.pembelian_id)
            elif detail.penjualan_id:
                processed_penjualan_ids.add(detail.penjualan_id)

        # Delete payment details first (due to foreign key constraints)
        for detail in pembayaran.pembayaran_details:
            db.delete(detail)

        # Delete the main payment record
        db.delete(pembayaran)
        db.commit()

        # Update payment status for all affected records after deletion
        for pembelian_id in processed_pembelian_ids:
            update_payment_status(db, pembelian_id, PembayaranPengembalianType.PEMBELIAN)

        for penjualan_id in processed_penjualan_ids:
            update_payment_status(db, penjualan_id, PembayaranPengembalianType.PENJUALAN)

        return {"message": "Pembayaran deleted successfully"}

    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error deleting pembayaran: {str(e)}")

@router.get("/{pembayaran_id}/details", response_model=List[PembayaranDetailResponse])
def get_pembayaran_details(pembayaran_id: int, db: Session = Depends(get_db)):
    """Get payment details for a specific payment"""

    pembayaran = db.query(Pembayaran).filter(
        Pembayaran.id == pembayaran_id,
        ).first()

    if not pembayaran:
        raise HTTPException(status_code=404, detail="Pembayaran not found")

    details = db.query(PembayaranDetails).options(
        joinedload(PembayaranDetails.pembelian_rel),
        joinedload(PembayaranDetails.penjualan_rel)
    ).filter(PembayaranDetails.pembayaran_id == pembayaran_id).all()

    return details

@router.put("/{pembayaran_id}/draft")
def revert_to_draft(pembayaran_id: int, db: Session = Depends(get_db)):
    """Revert an active payment back to draft status"""

    pembayaran = db.query(Pembayaran).filter(
        Pembayaran.id == pembayaran_id,
        ).first()

    if not pembayaran:
        raise HTTPException(status_code=404, detail="Pembayaran not found")

    if pembayaran.status != StatusPembelianEnum.ACTIVE:
        raise HTTPException(status_code=400, detail="Only active payments can be reverted to draft")

    # Store reference info for status update
    reference_ids = []
    for detail in pembayaran.pembayaran_details:
        if detail.pembelian_id:
            reference_ids.append((detail.pembelian_id, PembayaranPengembalianType.PEMBELIAN))
        elif detail.penjualan_id:
            reference_ids.append((detail.penjualan_id, PembayaranPengembalianType.PENJUALAN))

    # Revert to draft
    pembayaran.status = StatusPembelianEnum.DRAFT

    # Update payment status for all related records (recalculate without this payment)
    for reference_id, reference_type in reference_ids:
        update_payment_status(db, reference_id, reference_type)

    db.commit()
    db.refresh(pembayaran)

    return {"message": "Pembayaran reverted to draft successfully", "pembayaran": pembayaran}