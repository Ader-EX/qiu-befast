from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func, cast, Integer
from typing import List, Optional
from datetime import datetime, time, date
from decimal import Decimal

from database import get_db
from models.AuditTrail import AuditEntityEnum
from models.Pengembalian import Pengembalian, PengembalianDetails
from models.Pembelian import Pembelian, StatusPembayaranEnum, StatusPembelianEnum
from models.Penjualan import Penjualan
from routes.pembayaran_routes import update_payment_status  # <-- reuse the single status engine
from schemas.PembayaranSchemas import PembayaranPengembalianType
from schemas.PengembalianSchema import (
    PengembalianCreate, PengembalianUpdate, PengembalianResponse,
    PengembalianListResponse, PengembalianDetailResponse
)
from services.audit_services import AuditService
from utils import generate_unique_record_number, get_current_user_name

router = APIRouter()


def recalc_return_and_update_payment_status(db: Session, reference_id: int, reference_type: PembayaranPengembalianType, no_pengembalian : str, user_name  : str) -> None:
    """
    1) Recalculate and persist total_return on the referenced record (Pembelian/Penjualan)
       from ACTIVE pengembalian rows.
    2) Delegate to update_payment_status (which uses total_paid + total_return to set statuses).
    """
    if reference_type == PembayaranPengembalianType.PEMBELIAN:
        record = db.query(Pembelian).filter(Pembelian.id == reference_id).first()
        detail_filter = (PengembalianDetails.pembelian_id == reference_id)
    else:
        record = db.query(Penjualan).filter(Penjualan.id == reference_id).first()
        detail_filter = (PengembalianDetails.penjualan_id == reference_id)

    if not record:
        return

    total_returns = (
        db.query(func.coalesce(func.sum(PengembalianDetails.total_return), 0))
          .join(Pengembalian, PengembalianDetails.pengembalian_id == Pengembalian.id)
          .filter(Pengembalian.status == StatusPembelianEnum.ACTIVE)
          .filter(detail_filter)
          .scalar()
        or Decimal("0.00")
    )

    # Persist recalculated total_return on the referenced document
    record.total_return = Decimal(str(total_returns))
    db.flush()  # ensure the new total_return is visible to update_payment_status

    # Let the shared payment status function compute statuses using total_paid + total_return
    update_payment_status(db, reference_id, reference_type,user_name,no_pengembalian, "Pengembalian")



@router.post("", response_model=PengembalianResponse)
def create_pengembalian(pengembalian_data: PengembalianCreate, db: Session = Depends(get_db), user_name: str = Depends(get_current_user_name)):
    """Create a new return record (DRAFT)"""

    audit_service  = AuditService(db)
    # Validate return details exist
    if not pengembalian_data.pengembalian_details or len(pengembalian_data.pengembalian_details) == 0:
        raise HTTPException(status_code=400, detail="Return details are required")

    # Validate reference type consistency and check if records exist
    for detail in pengembalian_data.pengembalian_details:
        if pengembalian_data.reference_type == PembayaranPengembalianType.PEMBELIAN:
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

    # Create return record - EXCLUDE total_paid from pengembalian_dict
    pengembalian_dict = pengembalian_data.model_dump(exclude={'pengembalian_details'})
    pengembalian_dict.pop('total_return', None)  # ensure not on header

    pengembalian = Pengembalian(**pengembalian_dict)

    # Generate unique return number based on type
    if pengembalian_data.reference_type == PembayaranPengembalianType.PEMBELIAN:
        pengembalian.no_pengembalian = generate_unique_record_number(db, Pengembalian, "QP/RET")
    else:
        pengembalian.no_pengembalian = generate_unique_record_number(db, Pengembalian, "QP/RET")

    pengembalian.created_at = datetime.now()
    pengembalian.status = StatusPembelianEnum.DRAFT

    db.add(pengembalian)
    db.flush()

    total_paid = sum(detail_data.total_return for detail_data in pengembalian_data.pengembalian_details)
    # Create return details
    for detail_data in pengembalian_data.pengembalian_details:
        detail = PengembalianDetails(
            pengembalian_id=pengembalian.id,
            **detail_data.model_dump()
        )
        db.add(detail)

    audit_service.default_log(
        entity_id=pengembalian.id,
        entity_type=AuditEntityEnum.PENGEMBALIAN,
        description=f"Pengembalian {pengembalian.no_pengembalian} dibuat, total : Rp{total_paid}",
        user_name=user_name
    )

    db.commit()
    db.refresh(pengembalian)

    return pengembalian


@router.get("", response_model=PengembalianListResponse)
def get_pengembalians(
        skip: int = Query(0, ge=0),
        limit: int = Query(100, ge=1, le=1000),
        reference_type: Optional[PembayaranPengembalianType] = None,
        status: Optional[StatusPembelianEnum] = None,
        db: Session = Depends(get_db),
        search_key: Optional[str] = Query(None, description="Search by return number"),
        to_date : Optional[date] = Query(None, description="Filter by date"),
        from_date : Optional[date] = Query(None, description="Filter by date"),
):
    """Get list of return records with filtering"""

    query = db.query(Pengembalian).filter().order_by(
        cast(func.substr(Pengembalian.no_pengembalian,
                         func.length(Pengembalian.no_pengembalian) - 3), Integer).desc(),
        cast(func.substr(Pengembalian.no_pengembalian,
                         func.length(Pengembalian.no_pengembalian) - 6, 2), Integer).desc(),
        cast(func.substr(Pengembalian.no_pengembalian, 7, 4), Integer).desc()
    )
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

    if reference_type and reference_type != "ALL":
        query = query.filter(Pengembalian.reference_type == reference_type)

    if status and status != "ALL":
        query = query.filter(Pengembalian.status == status)
    if search_key:
        query = query.filter(Pengembalian.no_pengembalian.ilike(f"%{search_key}%"))

    total = query.count()

    pengembalians = query.options(
        joinedload(Pengembalian.pengembalian_details).joinedload(PengembalianDetails.pembelian_rel),
        joinedload(Pengembalian.pengembalian_details).joinedload(PengembalianDetails.penjualan_rel),
        joinedload(Pengembalian.customer_rel),
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
        joinedload(Pengembalian.pengembalian_details).joinedload(PengembalianDetails.pembelian_rel),
        joinedload(Pengembalian.pengembalian_details).joinedload(PengembalianDetails.penjualan_rel),
        joinedload(Pengembalian.customer_rel),
        joinedload(Pengembalian.warehouse_rel),
        joinedload(Pengembalian.curr_rel)
    ).filter(
        Pengembalian.id == pengembalian_id,
    ).first()

    if not pengembalian:
        raise HTTPException(status_code=404, detail="Pengembalian not found")

    return pengembalian


@router.put("/{pengembalian_id}/finalize")
def finalize_pengembalian(pengembalian_id: int, db: Session = Depends(get_db), user_name : str = Depends(get_current_user_name)):
    """Finalize return record by ID"""

    pengembalian = db.query(Pengembalian).filter(
        Pengembalian.id == pengembalian_id,
    ).first()

    if not pengembalian:
        raise HTTPException(status_code=404, detail="Pengembalian not found")

    if pengembalian.status == StatusPembelianEnum.ACTIVE:
        raise HTTPException(status_code=400, detail="Pengembalian already finalized")

    if pengembalian.status != StatusPembelianEnum.DRAFT:
        raise HTTPException(status_code=400, detail="Only draft returns can be finalized")

    pengembalian.status = StatusPembelianEnum.ACTIVE
    db.flush()

    # Recalc returns and update payment status for each affected reference
    for detail in pengembalian.pengembalian_details:
        if detail.pembelian_id:
            recalc_return_and_update_payment_status(db, detail.pembelian_id, PembayaranPengembalianType.PEMBELIAN,pengembalian.no_pengembalian,user_name=user_name)
        elif detail.penjualan_id:
            recalc_return_and_update_payment_status(db, detail.penjualan_id, PembayaranPengembalianType.PENJUALAN,pengembalian.no_pengembalian, user_name=user_name)

    db.commit()
    db.refresh(pengembalian)

    return {"message": "Pengembalian finalized successfully", "pengembalian": pengembalian}


@router.put("/{pengembalian_id}", response_model=PengembalianResponse)
def update_pengembalian(
        pengembalian_id: int,
        pengembalian_data: PengembalianUpdate,
        db: Session = Depends(get_db),
        user_name : str = Depends(get_current_user_name)
):
    """Update return record"""

    pengembalian = db.query(Pengembalian).filter(
        Pengembalian.id == pengembalian_id,
    ).first()

    if not pengembalian:
        raise HTTPException(status_code=404, detail="Pengembalian not found")

    # Only allow updates if return is in draft status
    if pengembalian.status != StatusPembelianEnum.DRAFT:
        raise HTTPException(status_code=400, detail="Only draft returns can be updated")

    # Store old reference info for status update
    old_details = [(detail.pembelian_id, detail.penjualan_id) for detail in pengembalian.pengembalian_details]
    old_reference_type = pengembalian.reference_type

    # Check if reference type is changing
    reference_type_changed = (
        pengembalian_data.reference_type is not None and
        pengembalian_data.reference_type != old_reference_type
    )

    # If reference type is changing, validate the new data consistency
    if reference_type_changed:
        new_reference_type = pengembalian_data.reference_type

        if new_reference_type == PembayaranPengembalianType.PENJUALAN:
            if pengembalian_data.customer_id is None and pengembalian.customer_id is None:
                raise HTTPException(
                    status_code=400,
                    detail="customer_id is required when reference_type is PENJUALAN"
                )
            if pengembalian_data.vendor_id is not None:
                raise HTTPException(
                    status_code=400,
                    detail="vendor_id should not be set when reference_type is PENJUALAN"
                )
        else:  # PEMBELIAN
            if pengembalian_data.vendor_id is None and pengembalian.vendor_id is None:
                raise HTTPException(
                    status_code=400,
                    detail="vendor_id is required when reference_type is PEMBELIAN"
                )
            if pengembalian_data.customer_id is not None:
                raise HTTPException(
                    status_code=400,
                    detail="customer_id should not be set when reference_type is PEMBELIAN"
                )

        # Validate return details consistency with new reference type
        if pengembalian_data.pengembalian_details:
            for detail in pengembalian_data.pengembalian_details:
                if new_reference_type == PembayaranPengembalianType.PENJUALAN:
                    if not detail.penjualan_id:
                        raise HTTPException(
                            status_code=400,
                            detail="penjualan_id is required in return details when reference_type is PENJUALAN"
                        )
                    if detail.pembelian_id:
                        raise HTTPException(
                            status_code=400,
                            detail="pembelian_id should not be set when reference_type is PENJUALAN"
                        )
                else:  # PEMBELIAN
                    if not detail.pembelian_id:
                        raise HTTPException(
                            status_code=400,
                            detail="pembelian_id is required in return details when reference_type is PEMBELIAN"
                        )
                    if detail.penjualan_id:
                        raise HTTPException(
                            status_code=400,
                            detail="penjualan_id should not be set when reference_type is PEMBELIAN"
                        )

    # If reference type changed or return details are provided, validate and check existence
    if pengembalian_data.pengembalian_details:
        current_reference_type = pengembalian_data.reference_type or pengembalian.reference_type

        for detail in pengembalian_data.pengembalian_details:
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

    # Update main pengembalian fields
    pengembalian_dict = pengembalian_data.model_dump(exclude={'pengembalian_details'}, exclude_unset=True)

    # If reference type is changing, clear the opposite ID field
    if reference_type_changed:
        if pengembalian_data.reference_type == PembayaranPengembalianType.PENJUALAN:
            pengembalian.vendor_id = None
        else:  # PEMBELIAN
            pengembalian.customer_id = None

    for field, value in pengembalian_dict.items():
        setattr(pengembalian, field, value)

    # Always delete and recreate return details if provided or if reference type changed
    if pengembalian_data.pengembalian_details is not None or reference_type_changed:
        # Delete existing details
        for detail in pengembalian.pengembalian_details:
            db.delete(detail)
        db.flush()

        # Create new details (only if provided)
        if pengembalian_data.pengembalian_details:
            for detail_data in pengembalian_data.pengembalian_details:
                detail = PengembalianDetails(
                    pengembalian_id=pengembalian.id,
                    **detail_data.model_dump()
                )
                db.add(detail)

    db.commit()
    db.refresh(pengembalian)

    # Recalc & update statuses for old references (in case details/reference mapping changed)
    for old_pembelian_id, old_penjualan_id in old_details:
        if old_pembelian_id:
            recalc_return_and_update_payment_status(db, old_pembelian_id, PembayaranPengembalianType.PEMBELIAN,pengembalian.no_pengembalian,user_name=user_name)
        elif old_penjualan_id:
            recalc_return_and_update_payment_status(db, old_penjualan_id, PembayaranPengembalianType.PENJUALAN,pengembalian.no_pengembalian, user_name=user_name)

    db.commit()  # persist the recalculated statuses
    return pengembalian


@router.delete("/{pengembalian_id}")
def delete_pengembalian(pengembalian_id: int, db: Session = Depends(get_db)):
    """Delete return record by ID"""
    pengembalian = db.query(Pengembalian).filter(
        Pengembalian.id == pengembalian_id,
    ).first()

    if not pengembalian:
        raise HTTPException(status_code=404, detail="Pengembalian not found")

    try:
        # Store reference info for status update
        processed_pembelian_ids = set()
        processed_penjualan_ids = set()

        for detail in pengembalian.pengembalian_details:
            if detail.pembelian_id:
                processed_pembelian_ids.add(detail.pembelian_id)
            elif detail.penjualan_id:
                processed_penjualan_ids.add(detail.penjualan_id)

        # Delete return details first (due to foreign key constraints)
        for detail in pengembalian.pengembalian_details:
            db.delete(detail)

        # Delete the main return record
        db.delete(pengembalian)
        db.commit()

        # Recalc & update statuses for all affected records after deletion
        for pembelian_id in processed_pembelian_ids:
            recalc_return_and_update_payment_status(db, pembelian_id, PembayaranPengembalianType.PEMBELIAN,pengembalian.no_pengembalian)

        for penjualan_id in processed_penjualan_ids:
            recalc_return_and_update_payment_status(db, penjualan_id, PembayaranPengembalianType.PENJUALAN,pengembalian.no_pengembalian)

        db.commit()
        return {"message": "Pengembalian deleted successfully"}

    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error deleting pengembalian: {str(e)}")


@router.get("/{pengembalian_id}/details", response_model=List[PengembalianDetailResponse])
def get_pengembalian_details(pengembalian_id: int, db: Session = Depends(get_db)):
    """Get return details for a specific return"""

    pengembalian = db.query(Pengembalian).filter(
        Pengembalian.id == pengembalian_id,
    ).first()

    if not pengembalian:
        raise HTTPException(status_code=404, detail="Pengembalian not found")

    details = db.query(PengembalianDetails).options(
        joinedload(PengembalianDetails.pembelian_rel),
        joinedload(PengembalianDetails.penjualan_rel)
    ).filter(PengembalianDetails.pengembalian_id == pengembalian_id).all()

    return details


@router.put("/{pengembalian_id}/draft")
def revert_to_draft(pengembalian_id: int, db: Session = Depends(get_db)):
    """Revert an active return back to draft status"""

    pengembalian = db.query(Pengembalian).filter(
        Pengembalian.id == pengembalian_id,
    ).first()

    if not pengembalian:
        raise HTTPException(status_code=404, detail="Pengembalian not found")

    if pengembalian.status != StatusPembelianEnum.ACTIVE:
        raise HTTPException(status_code=400, detail="Only active returns can be reverted to draft")

    # Store reference info for status update
    reference_ids = []
    for detail in pengembalian.pengembalian_details:
        if detail.pembelian_id:
            reference_ids.append((detail.pembelian_id, PembayaranPengembalianType.PEMBELIAN))
        elif detail.penjualan_id:
            reference_ids.append((detail.penjualan_id, PembayaranPengembalianType.PENJUALAN))

    # Revert to draft
    pengembalian.status = StatusPembelianEnum.DRAFT
    db.flush()

    # Update payment status for all related records (recalculate without this return)
    for reference_id, reference_type in reference_ids:
        recalc_return_and_update_payment_status(db, reference_id, reference_type,pengembalian.no_pengembalian)

    db.commit()
    db.refresh(pengembalian)

    return {"message": "Pengembalian reverted to draft successfully", "pengembalian": pengembalian}
