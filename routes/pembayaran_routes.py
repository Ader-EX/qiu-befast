from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import or_, and_, func
from typing import List, Optional
from datetime import datetime, date
from decimal import Decimal

from database import get_db
from models.Pembayaran import Pembayaran, PembayaranDetails, PembayaranPengembalianType
from models.Pembelian import Pembelian, StatusPembayaranEnum, StatusPembelianEnum
from models.Penjualan import Penjualan
from schemas.PembayaranSchemas import (
    PembayaranCreate, PembayaranUpdate, PembayaranResponse,
    PembayaranListResponse, PembayaranFilter, PembayaranSummary,
    PembayaranDailySummary
)
from utils import soft_delete_record, generate_unique_record_number

router = APIRouter()

# Helper function to update payment status
def update_payment_status(db: Session, reference_id: int, reference_type: PembayaranPengembalianType):
    """Update payment and completion status based on total payments"""
    if reference_type == PembayaranPengembalianType.PEMBELIAN:
        record = db.query(Pembelian).filter(Pembelian.id == reference_id).first()
    else:
        record = db.query(Penjualan).filter(Penjualan.id == reference_id).first()

    if not record:
        return

    # Calculate total paid for this record through PembayaranDetails
    total_payments = db.query(func.sum(PembayaranDetails.total_paid)).join(
        Pembayaran, PembayaranDetails.pembayaran_id == Pembayaran.id
    ).filter(
        and_(
            PembayaranDetails.pembelian_id == reference_id if reference_type == PembayaranPengembalianType.PEMBELIAN else PembayaranDetails.penjualan_id == reference_id,

        )
    ).scalar() or Decimal('0.00')

    record.total_paid = total_payments

    total_outstanding = record.total_price - (record.total_paid + record.total_return)

    if total_outstanding <= 0:
        record.status_pembayaran = StatusPembayaranEnum.PAID
        if reference_type == PembayaranPengembalianType.PEMBELIAN:
            record.status_pembelian = StatusPembelianEnum.COMPLETED
        else:
            record.status_penjualan = StatusPembelianEnum.COMPLETED  # Assuming similar enum exists
    elif record.total_paid > 0:
        record.status_pembayaran = StatusPembayaranEnum.HALF_PAID
    else:
        record.status_pembayaran = StatusPembayaranEnum.UNPAID

    db.commit()

@router.post("/", response_model=PembayaranResponse)
def create_pembayaran(pembayaran_data: PembayaranCreate, db: Session = Depends(get_db)):
    """Create a new payment record"""

    # Validate payment details exist
    if not pembayaran_data.pembayaran_details or len(pembayaran_data.pembayaran_details) == 0:
        raise HTTPException(status_code=400, detail="Payment details are required")

    # Validate reference type consistency
    for detail in pembayaran_data.pembayaran_details:
        if pembayaran_data.reference_type == PembayaranPengembalianType.PEMBELIAN:
            if not detail.pembelian_id:
                raise HTTPException(status_code=400, detail="pembelian_id is required for PEMBELIAN type")

            pembelian = db.query(Pembelian).filter(
                Pembelian.id == detail.pembelian_id,
                Pembelian.is_deleted == False,
                Pembelian.status_pembelian == StatusPembelianEnum.ACTIVE
            ).first()
            if not pembelian:
                raise HTTPException(status_code=404, detail=f"Active Pembelian with ID {detail.pembelian_id} not found")

        else:
            if not detail.penjualan_id:
                raise HTTPException(status_code=400, detail="penjualan_id is required for PENJUALAN type")

            penjualan = db.query(Penjualan).filter(
                Penjualan.id == detail.penjualan_id,
                Penjualan.is_deleted == False,
                Penjualan.status_penjualan == StatusPembelianEnum.ACTIVE
            ).first()
            if not penjualan:
                raise HTTPException(status_code=404, detail=f"Active Penjualan with ID {detail.penjualan_id} not found")

    # Create payment record
    pembayaran_dict = pembayaran_data.dict(exclude={'pembayaran_details'})
    pembayaran = Pembayaran(**pembayaran_dict)

    if pembayaran_data.reference_type == PembayaranPengembalianType.PEMBELIAN:
        pembayaran.no_pembayaran = generate_unique_record_number(db, Pembayaran, "QP/AR")
    else :
        pembayaran.no_pembayaran = generate_unique_record_number(db, Pembayaran, "QP/AP")

    pembayaran.created_at = datetime.now()

    db.add(pembayaran)
    db.flush()

    # Create payment details
    for detail_data in pembayaran_data.pembayaran_details:
        detail = PembayaranDetails(
            pembayaran_id=pembayaran.id,
            **detail_data.dict()
        )
        db.add(detail)

    db.commit()
    db.refresh(pembayaran)


    return pembayaran

@router.get("/", response_model=PembayaranListResponse)
def get_pembayarans(
        skip: int = Query(0, ge=0),
        limit: int = Query(100, ge=1, le=1000),
        reference_type: Optional[PembayaranPengembalianType] = None,
        customer_id: Optional[str] = None,
        vendor_id: Optional[str] = None,
        warehouse_id: Optional[int] = None,
        currency_id: Optional[int] = None,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
        min_amount: Optional[Decimal] = None,
        max_amount: Optional[Decimal] = None,
        db: Session = Depends(get_db)
):
    """Get list of payment records with filtering"""

    query = db.query(Pembayaran).filter(Pembayaran.is_deleted == False)

    # Apply filters
    if reference_type:
        query = query.filter(Pembayaran.reference_type == reference_type)

    if customer_id:
        query = query.filter(Pembayaran.customer_id == customer_id)

    if vendor_id:
        query = query.filter(Pembayaran.vendor_id == vendor_id)

    if warehouse_id:
        query = query.filter(Pembayaran.warehouse_id == warehouse_id)

    if currency_id:
        query = query.filter(Pembayaran.currency_id == currency_id)

    if date_from:
        query = query.filter(Pembayaran.payment_date >= date_from)

    if date_to:
        query = query.filter(Pembayaran.payment_date <= date_to)

    if min_amount:
        query = query.filter(Pembayaran.total_paid >= min_amount)

    if max_amount:
        query = query.filter(Pembayaran.total_paid <= max_amount)

    # Get total count
    total = query.count()

    # Get paginated results with relationships
    pembayarans = query.options(
        joinedload(Pembayaran.pembayaran_details).joinedload(PembayaranDetails.pembelian_rel),
        joinedload(Pembayaran.pembayaran_details).joinedload(PembayaranDetails.penjualan_rel),
        joinedload(Pembayaran.customer_rel),
        joinedload(Pembayaran.warehouse_rel),
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


    pembayaran = db.query(Pembayaran).options(
        joinedload(Pembayaran.pembayaran_details).joinedload(PembayaranDetails.pembelian_rel),
        joinedload(Pembayaran.pembayaran_details).joinedload(PembayaranDetails.penjualan_rel),
        joinedload(Pembayaran.customer_rel),
        joinedload(Pembayaran.warehouse_rel),
        joinedload(Pembayaran.curr_rel)
    ).filter(
        Pembayaran.id == pembayaran_id,
        Pembayaran.is_deleted == False
    ).first()

    if not pembayaran:
        raise HTTPException(status_code=404, detail="Pembayaran not found")

    return pembayaran

@router.put("/{pembayaran_id}/finalize")
async  def finalize_pembayaran(pembayaran_id : int, db:Session = Depends(get_db)):
    """Finalize payment record by ID"""

    pembayaran = db.query(Pembayaran).filter(
        Pembayaran.id == pembayaran_id,

    ).first()

    if not pembayaran:
        raise HTTPException(status_code=404, detail="Pembayaran not found")

    if pembayaran.status == StatusPembelianEnum.ACTIVE:
        raise HTTPException(status_code=400, detail="Pembayaran already finalized")

    # Mark as finalized
    pembayaran.status = StatusPembelianEnum.ACTIVE
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
        Pembayaran.is_deleted == False
    ).first()

    if not pembayaran:
        raise HTTPException(status_code=404, detail="Pembayaran not found")

    # Store old reference info for status update
    old_details = [(detail.pembelian_id, detail.penjualan_id) for detail in pembayaran.pembayaran_details]

    # Update main pembayaran fields
    pembayaran_dict = pembayaran_data.dict(exclude={'pembayaran_details'}, exclude_unset=True)
    for field, value in pembayaran_dict.items():
        setattr(pembayaran, field, value)

    # Update payment details if provided
    if pembayaran_data.pembayaran_details is not None:
        # Delete existing details
        for detail in pembayaran.pembayaran_details:
            db.delete(detail)

        # Create new details
        for detail_data in pembayaran_data.pembayaran_details:
            detail = PembayaranDetails(
                pembayaran_id=pembayaran.id,
                **detail_data.dict()
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

    # Update payment status for current references
    for detail in pembayaran.pembayaran_details:
        if detail.pembelian_id:
            update_payment_status(db, detail.pembelian_id, PembayaranPengembalianType.PEMBELIAN)
        elif detail.penjualan_id:
            update_payment_status(db, detail.penjualan_id, PembayaranPengembalianType.PENJUALAN)

    return pembayaran

@router.delete("/{pembayaran_id}")
def delete_pembayaran(pembayaran_id: int, db: Session = Depends(get_db)):
    """Soft delete payment record and update related pembelian/penjualan totals"""

    pembayaran = db.query(Pembayaran).filter(
        Pembayaran.id == pembayaran_id,
        Pembayaran.is_deleted == False
    ).first()

    if not pembayaran:
        raise HTTPException(status_code=404, detail="Pembayaran not found")

    try:
        # Process each pembayaran detail to subtract amounts from related records
        processed_pembelian_ids = set()
        processed_penjualan_ids = set()

        for detail in pembayaran.pembayaran_details:
            if detail.pembelian_id:
                # Only subtract from ACTIVE pembelian
                pembelian = db.query(Pembelian).filter(
                    Pembelian.id == detail.pembelian_id,
                    Pembelian.is_deleted == False,
                    Pembelian.status_pembelian == StatusPembelianEnum.ACTIVE
                ).first()

                if pembelian:
                    pembelian.total_paid = max(0, pembelian.total_paid - detail.total_paid)
                    processed_pembelian_ids.add(detail.pembelian_id)

            elif detail.penjualan_id:
                # Only subtract from ACTIVE penjualan
                penjualan = db.query(Penjualan).filter(
                    Penjualan.id == detail.penjualan_id,
                    Penjualan.is_deleted == False,
                    Penjualan.status_penjualan == StatusPembelianEnum.ACTIVE  # Assuming similar enum
                ).first()

                if penjualan:
                    if pembayaran.reference_type == PembayaranPengembalianType.PENGEMBALIAN:
                        # For returns, subtract from total_return
                        penjualan.total_return = max(0, penjualan.total_return - detail.total_paid)
                    else:
                        # For payments, subtract from total_paid
                        penjualan.total_paid = max(0, penjualan.total_paid - detail.total_paid)
                    processed_penjualan_ids.add(detail.penjualan_id)

        # Soft delete the pembayaran
        pembayaran.is_deleted = True
        pembayaran.deleted_at = datetime.now()

        # Commit all changes
        db.commit()

        # Update payment status for all affected records
        for pembelian_id in processed_pembelian_ids:
            update_payment_status(db, pembelian_id, PembayaranPengembalianType.PEMBELIAN)

        for penjualan_id in processed_penjualan_ids:
            update_payment_status(db, penjualan_id, PembayaranPengembalianType.PENJUALAN)

        return {"message": "Pembayaran deleted successfully"}

    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error deleting pembayaran: {str(e)}")

@router.get("/summary/total", response_model=List[PembayaranSummary])
def get_payment_summary(
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
        db: Session = Depends(get_db)
):
    """Get payment summary grouped by reference type"""

    query = db.query(
        Pembayaran.reference_type,
        func.sum(Pembayaran.total_paid).label('total_payments'),
        func.count(Pembayaran.id).label('count')
    ).filter(Pembayaran.is_deleted == False)

    if date_from:
        query = query.filter(Pembayaran.payment_date >= date_from)
    if date_to:
        query = query.filter(Pembayaran.payment_date <= date_to)

    results = query.group_by(Pembayaran.reference_type).all()

    return [
        PembayaranSummary(
            reference_type=result.reference_type,
            total_payments=result.total_payments or Decimal('0.00'),
            count=result.count
        )
        for result in results
    ]

@router.get("/summary/daily", response_model=List[PembayaranDailySummary])
def get_daily_payment_summary(
        date_from: Optional[date] = None,
        date_to: Optional[date] = None,
        db: Session = Depends(get_db)
):
    """Get daily payment summary"""

    query = db.query(
        func.date(Pembayaran.payment_date).label('date'),
        func.sum(
            func.case(
                [(Pembayaran.reference_type == PembayaranPengembalianType.PEMBELIAN, Pembayaran.total_paid)],
                else_=0
            )
        ).label('total_pembelian'),
        func.sum(
            func.case(
                [(Pembayaran.reference_type == PembayaranPengembalianType.PENJUALAN, Pembayaran.total_paid)],
                else_=0
            )
        ).label('total_penjualan'),
        func.sum(
            func.case(
                [(Pembayaran.reference_type == PembayaranPengembalianType.PEMBELIAN, 1)],
                else_=0
            )
        ).label('count_pembelian'),
        func.sum(
            func.case(
                [(Pembayaran.reference_type == PembayaranPengembalianType.PENJUALAN, 1)],
                else_=0
            )
        ).label('count_penjualan')
    ).filter(Pembayaran.is_deleted == False)

    if date_from:
        query = query.filter(func.date(Pembayaran.payment_date) >= date_from)
    if date_to:
        query = query.filter(func.date(Pembayaran.payment_date) <= date_to)

    results = query.group_by(func.date(Pembayaran.payment_date)).order_by('date').all()

    return [
        PembayaranDailySummary(
            date=result.date,
            total_pembelian=result.total_pembelian or Decimal('0.00'),
            total_penjualan=result.total_penjualan or Decimal('0.00'),
            count_pembelian=result.count_pembelian,
            count_penjualan=result.count_penjualan
        )
        for result in results
    ]