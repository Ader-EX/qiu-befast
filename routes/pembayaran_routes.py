from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import or_, and_, func
from typing import List, Optional
from datetime import datetime, date
from decimal import Decimal

from database import get_db
from models.Pembayaran import Pembayaran, PembayaranPengembalianType
from models.Pembelian import Pembelian, StatusPembayaranEnum, StatusPembelianEnum
from models.Penjualan import Penjualan
from schemas.PembayaranSchemas import (
    PembayaranCreate, PembayaranUpdate, PembayaranResponse, 
    PembayaranListResponse, PembayaranFilter, PembayaranSummary,
    PembayaranDailySummary
)
from utils import soft_delete_record


router = FastAPI()
# Helper function to update payment status
def update_payment_status(db: Session, reference_id: int, reference_type: PembayaranPengembalianType):
    """Update payment and completion status based on total payments"""
    if reference_type == PembayaranPengembalianType.PEMBELIAN:
        record = db.query(Pembelian).filter(Pembelian.id == reference_id).first()
        id_field = 'pembelian_id'
    else:
        record = db.query(Penjualan).filter(Penjualan.id == reference_id).first()
        id_field = 'penjualan_id'
    
    if not record:
        return
    
    # Calculate total paid for this record
    total_payments = db.query(Pembayaran).filter(
        and_(
            getattr(Pembayaran, id_field) == reference_id,
            Pembayaran.is_deleted == False
        )
    ).all()
    
    total_paid = sum(payment.total_paid for payment in total_payments)
    record.total_paid = total_paid
    
    # Update payment status
    total_outstanding = record.total_price - (record.total_paid + record.total_return)
    
    if total_outstanding <= 0:
        record.status_pembayaran = StatusPembayaranEnum.PAID
        if reference_type == PembayaranPengembalianType.PEMBELIAN:
            record.status_pembelian = StatusPembelianEnum.COMPLETED
        else:
            record.status_penjualan = StatusPembelianEnum.COMPLETED
    elif record.total_paid > 0:
        record.status_pembayaran = StatusPembayaranEnum.HALF_PAID
    else:
        record.status_pembayaran = StatusPembayaranEnum.UNPAID
    
    db.commit()

@router.post("/", response_model=PembayaranResponse)
def create_pembayaran(pembayaran_data: PembayaranCreate, db: Session = Depends(get_db)):
    """Create a new payment record"""
    
    # Validate reference exists and get reference data
    if pembayaran_data.reference_type == PembayaranPengembalianType.PEMBELIAN:
        if not pembayaran_data.pembelian_id:
            raise HTTPException(status_code=400, detail="pembelian_id is required for PEMBELIAN type")
            
        reference = db.query(Pembelian).filter(
            Pembelian.id == pembayaran_data.pembelian_id,
            Pembelian.is_deleted == False
        ).first()
        if not reference:
            raise HTTPException(status_code=404, detail="Pembelian not found")
        
        # Auto-fill vendor and warehouse if not provided
        if not pembayaran_data.vendor_id and reference.vendor_id:
            pembayaran_data.vendor_id = reference.vendor_id
        if not pembayaran_data.warehouse_id and reference.warehouse_id:
            pembayaran_data.warehouse_id = reference.warehouse_id
            
    else:  # PENJUALAN
        if not pembayaran_data.penjualan_id:
            raise HTTPException(status_code=400, detail="penjualan_id is required for PENJUALAN type")
            
        reference = db.query(Penjualan).filter(
            Penjualan.id == pembayaran_data.penjualan_id,
            Penjualan.is_deleted == False
        ).first()
        if not reference:
            raise HTTPException(status_code=404, detail="Penjualan not found")
            
        # Auto-fill customer and warehouse if not provided
        if not pembayaran_data.customer_id and reference.customer_id:
            pembayaran_data.customer_id = reference.customer_id
        if not pembayaran_data.warehouse_id and reference.warehouse_id:
            pembayaran_data.warehouse_id = reference.warehouse_id
    
    # Create payment record
    pembayaran = Pembayaran(**pembayaran_data.dict())
    pembayaran.created_at = datetime.now()
    
    db.add(pembayaran)
    db.commit()
    db.refresh(pembayaran)
    
    # Update payment status of the referenced record
    reference_id = pembayaran_data.pembelian_id or pembayaran_data.penjualan_id
    update_payment_status(db, reference_id, pembayaran_data.reference_type)
    
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
        joinedload(Pembayaran.pembelian_rel),
        joinedload(Pembayaran.penjualan_rel),
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
    """Get specific payment record by ID"""
    
    pembayaran = db.query(Pembayaran).options(
        joinedload(Pembayaran.pembelian_rel),
        joinedload(Pembayaran.penjualan_rel),
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
    old_pembelian_id = pembayaran.pembelian_id
    old_penjualan_id = pembayaran.penjualan_id
    old_reference_type = pembayaran.reference_type
    
    # Update fields
    for field, value in pembayaran_data.dict(exclude_unset=True).items():
        setattr(pembayaran, field, value)
    
    db.commit()
    db.refresh(pembayaran)
    
    # Update payment status for old reference
    if old_reference_type == PembayaranPengembalianType.PEMBELIAN and old_pembelian_id:
        update_payment_status(db, old_pembelian_id, old_reference_type)
    elif old_reference_type == PembayaranPengembalianType.PENJUALAN and old_penjualan_id:
        update_payment_status(db, old_penjualan_id, old_reference_type)
    
    # Update payment status for current reference
    current_reference_id = pembayaran.pembelian_id or pembayaran.penjualan_id
    if current_reference_id:
        update_payment_status(db, current_reference_id, pembayaran.reference_type)
    
    return pembayaran

@router.delete("/{pembayaran_id}")
def delete_pembayaran(pembayaran_id: int, db: Session = Depends(get_db)):
    """Soft delete payment record"""
    
    pembayaran = db.query(Pembayaran).filter(
        Pembayaran.id == pembayaran_id,
        Pembayaran.is_deleted == False
    ).first()
    
    if not pembayaran:
        raise HTTPException(status_code=404, detail="Pembayaran not found")
    
    # Store reference info for status update
    reference_id = pembayaran.pembelian_id if pembayaran.pembelian_id else pembayaran.penjualan_id
    reference_type = pembayaran.reference_type
    
    soft_delete_record(db,Pembayaran,pembayaran_id)
    
    db.commit()
    
    if reference_id:
        update_payment_status(db, reference_id, reference_type)
    
    return {"message": "Pembayaran deleted successfully"}

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