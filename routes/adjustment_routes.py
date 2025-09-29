from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import or_, func, cast, Integer
from typing import List, Optional
from datetime import datetime, date, time

from database import get_db
from models.AuditTrail import AuditEntityEnum
from models.StockAdjustment import StockAdjustment, StockAdjustmentItem, AdjustmentTypeEnum, StatusStockAdjustmentEnum
from models.Item import Item
from schemas.PaginatedResponseSchemas import PaginatedResponse
from schemas.StockAdjustmentSchemas import (
    StockAdjustmentCreate,
    StockAdjustmentUpdate,
    StockAdjustmentResponse,
    StockAdjustmentListResponse
)
from services.audit_services import AuditService
from utils import generate_unique_record_number, get_current_user_name

router = APIRouter()


def adjust_item_stock(db: Session, item_id: int, qty: int, adjustment_type: AdjustmentTypeEnum, no_adj: str, user_name: str):
    """Helper function to adjust item stock based on adjustment type"""
    audit_service = AuditService(db)

    item = db.query(Item).filter(Item.id == item_id, Item.is_deleted == False).first()

    if not item:
        raise HTTPException(status_code=404, detail=f"Item with ID {item_id} not found")

    old_stock = item.total_item

    if adjustment_type == AdjustmentTypeEnum.OUT:
        # Check if sufficient stock available
        if item.total_item < qty:
            raise HTTPException(
                status_code=400,
                detail=f"Insufficient stock for item {item.name}. Available: {item.total_item}, Required: {qty}"
            )
        item.total_item -= qty
        action = "dikurangi"
    else:  # IN
        item.total_item += qty
        action = "ditambahkan"

    new_stock = item.total_item

    # Log the stock change
    audit_service.default_log(
        entity_id=item.id,
        entity_type=AuditEntityEnum.ITEM,
        description=f"Stok item {item.name} {action} sebanyak {qty} (dari {old_stock} menjadi {new_stock}) - Adjustment: {no_adj
        }",
        user_name=user_name
    )

    db.flush()


@router.post("", response_model=StockAdjustmentResponse)
def create_stock_adjustment(
        adjustment_data: StockAdjustmentCreate,
        db: Session = Depends(get_db),
        user_name: str = Depends(get_current_user_name)
):
    """Create a new stock adjustment record in DRAFT status"""
    audit_service = AuditService(db)

    # Validate adjustment items exist
    if not adjustment_data.stock_adjustment_items or len(adjustment_data.stock_adjustment_items) == 0:
        raise HTTPException(status_code=400, detail="Stock adjustment items are required")

    # Validate adjustment type
    try:
        adj_type = AdjustmentTypeEnum(adjustment_data.adjustment_type)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid adjustment type. Must be IN or OUT")

    # Validate all items exist
    for item_data in adjustment_data.stock_adjustment_items:
        item = db.query(Item).filter(
            Item.id == item_data.item_id,
            Item.is_deleted == False
        ).first()
        if not item:
            raise HTTPException(status_code=404, detail=f"Item with ID {item_data.item_id} not found")

    # Create stock adjustment
    adjustment_dict = adjustment_data.model_dump(exclude={'stock_adjustment_items'})
    adjustment = StockAdjustment(**adjustment_dict)

    # Generate unique number
    adjustment.no_adjustment = generate_unique_record_number(db, StockAdjustment, "QP/SA")
    adjustment.status_adjustment = StatusStockAdjustmentEnum.DRAFT
    adjustment.created_at = datetime.now()

    db.add(adjustment)
    db.flush()

    # Create adjustment items
    total_qty = 0
    for item_data in adjustment_data.stock_adjustment_items:
        adj_item = StockAdjustmentItem(
            stock_adjustment_id=adjustment.id,
            **item_data.model_dump()
        )
        db.add(adj_item)
        total_qty += item_data.qty

    # Log audit
    audit_service.default_log(
        entity_id=adjustment.id,
        entity_type=AuditEntityEnum.STOCK_ADJUSTMENT,
        description=f"Stock Adjustment {adjustment.no_adjustment} dibuat (Draft), tipe: {adjustment_data.adjustment_type}, total items: {total_qty}",
        user_name=user_name
    )

    db.commit()
    db.refresh(adjustment)

    return adjustment


@router.get("", response_model=PaginatedResponse[StockAdjustmentResponse])
def get_stock_adjustments(
        skip: int = Query(0, ge=0),
        limit: int = Query(100, ge=1, le=1000),
        adjustment_type: Optional[str] = None,
        status: Optional[str] = None,
        search: Optional[str] = Query(None, description="Search by adjustment number"),
        from_date: Optional[date] = Query(None, description="Filter from date"),
        to_date: Optional[date] = Query(None, description="Filter to date"),
        db: Session = Depends(get_db)
):
    """Get list of stock adjustments with filtering"""

    # Base query
    query = db.query(StockAdjustment).filter(
        StockAdjustment.is_deleted == False
    )

    # Filter by adjustment type
    if adjustment_type and adjustment_type != "ALL":
        try:
            adj_type = AdjustmentTypeEnum(adjustment_type)
            query = query.filter(StockAdjustment.adjustment_type == adj_type)
        except ValueError:
            pass

    # Filter by status
    if status and status != "ALL":
        try:
            status_enum = StatusStockAdjustmentEnum(status)
            query = query.filter(StockAdjustment.status_adjustment == status_enum)
        except ValueError:
            pass

    # Filter by date range
    if from_date and to_date:
        query = query.filter(
            StockAdjustment.adjustment_date.between(from_date, to_date)
        )
    elif from_date:
        query = query.filter(StockAdjustment.adjustment_date >= from_date)
    elif to_date:
        query = query.filter(StockAdjustment.adjustment_date <= to_date)

    # Search by adjustment number
    if search:
        query = query.filter(StockAdjustment.no_adjustment.ilike(f"%{search}%"))

    # Get total count
    total = query.count()

    # Fetch paginated results with eager loading
    adjustments = (
        query
        .options(
            joinedload(StockAdjustment.stock_adjustment_items)
            .joinedload(StockAdjustmentItem.item_rel),
            joinedload(StockAdjustment.warehouse_rel)
        )
        .order_by(StockAdjustment.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )

    return PaginatedResponse(
        data=adjustments,
        total=total,
    )
@router.get("/{adjustment_id}", response_model=StockAdjustmentResponse)
def get_stock_adjustment(adjustment_id: int, db: Session = Depends(get_db)):
    """Get stock adjustment by ID"""

    adjustment = db.query(StockAdjustment).options(
        joinedload(StockAdjustment.stock_adjustment_items).joinedload(StockAdjustmentItem.item_rel),
        joinedload(StockAdjustment.warehouse_rel),
    ).filter(
        StockAdjustment.id == adjustment_id,
        StockAdjustment.is_deleted == False
    ).first()

    if not adjustment:
        raise HTTPException(status_code=404, detail="Stock adjustment not found")

    return adjustment


@router.put("/{adjustment_id}/finalize")
def finalize_stock_adjustment(
        adjustment_id: int,
        db: Session = Depends(get_db),
        user_name: str = Depends(get_current_user_name)
):
    """Finalize stock adjustment and apply stock changes"""
    audit_service = AuditService(db)

    adjustment = db.query(StockAdjustment).options(
        joinedload(StockAdjustment.stock_adjustment_items).joinedload(StockAdjustmentItem.item_rel)
    ).filter(
        StockAdjustment.id == adjustment_id,
        StockAdjustment.is_deleted == False
    ).first()

    if not adjustment:
        raise HTTPException(status_code=404, detail="Stock adjustment not found")

    if adjustment.status_adjustment == StatusStockAdjustmentEnum.ACTIVE:
        raise HTTPException(status_code=400, detail="Stock adjustment already finalized")

    if adjustment.status_adjustment != StatusStockAdjustmentEnum.DRAFT:
        raise HTTPException(status_code=400, detail="Only draft adjustments can be finalized")

    # Apply stock changes for each item
    for adj_item in adjustment.stock_adjustment_items:
        adjust_item_stock(
            db=db,
            item_id=adj_item.item_id,
            qty=adj_item.qty,
            adjustment_type=adjustment.adjustment_type,
            no_adj=adjustment.no_adjustment,
            user_name=user_name
        )

    # Update status to ACTIVE
    adjustment.status_adjustment = StatusStockAdjustmentEnum.ACTIVE
    adjustment.updated_at = datetime.now()

    # Log audit
    total_qty = sum(item.qty for item in adjustment.stock_adjustment_items)
    audit_service.default_log(
        entity_id=adjustment.id,
        entity_type=AuditEntityEnum.STOCK_ADJUSTMENT,
        description=f"Stock Adjustment {adjustment.no_adjustment} difinalisasi, tipe: {adjustment.adjustment_type.value}, total items: {total_qty}",
        user_name=user_name
    )

    db.commit()
    db.refresh(adjustment)

    return {"message": "Stock adjustment finalized successfully", "adjustment": adjustment}


@router.put("/{adjustment_id}", response_model=StockAdjustmentResponse)
def update_stock_adjustment(
        adjustment_id: int,
        adjustment_data: StockAdjustmentUpdate,
        db: Session = Depends(get_db),
        user_name: str = Depends(get_current_user_name)
):
    """Update stock adjustment (only allowed for DRAFT status)"""
    audit_service = AuditService(db)

    adjustment = db.query(StockAdjustment).filter(
        StockAdjustment.id == adjustment_id,
        StockAdjustment.is_deleted == False
    ).first()

    if not adjustment:
        raise HTTPException(status_code=404, detail="Stock adjustment not found")

    # Only allow updates if adjustment is in draft status
    if adjustment.status_adjustment != StatusStockAdjustmentEnum.DRAFT:
        raise HTTPException(status_code=400, detail="Only draft adjustments can be updated")

    # Validate items if provided
    if adjustment_data.stock_adjustment_items:
        for item_data in adjustment_data.stock_adjustment_items:
            item = db.query(Item).filter(
                Item.id == item_data.item_id,
                Item.is_deleted == False
            ).first()
            if not item:
                raise HTTPException(status_code=404, detail=f"Item with ID {item_data.item_id} not found")

    # Update main adjustment fields
    adjustment_dict = adjustment_data.model_dump(exclude={'stock_adjustment_items'}, exclude_unset=True)

    for field, value in adjustment_dict.items():
        setattr(adjustment, field, value)

    adjustment.updated_at = datetime.now()

    # Update adjustment items if provided
    if adjustment_data.stock_adjustment_items is not None:
        # Delete existing items
        for item in adjustment.stock_adjustment_items:
            db.delete(item)
        db.flush()

        # Create new items
        for item_data in adjustment_data.stock_adjustment_items:
            adj_item = StockAdjustmentItem(
                stock_adjustment_id=adjustment.id,
                **item_data.model_dump()
            )
            db.add(adj_item)

    # Log audit
    audit_service.default_log(
        entity_id=adjustment.id,
        entity_type=AuditEntityEnum.STOCK_ADJUSTMENT,
        description=f"Stock Adjustment {adjustment.no_adjustment} diupdate",
        user_name=user_name
    )

    db.commit()
    db.refresh(adjustment)

    return adjustment


@router.delete("/{adjustment_id}")
def delete_stock_adjustment(
        adjustment_id: int,
        db: Session = Depends(get_db),
        user_name: str = Depends(get_current_user_name)
):
    """Delete stock adjustment (only allowed for DRAFT status)"""
    audit_service = AuditService(db)

    adjustment = db.query(StockAdjustment).filter(
        StockAdjustment.id == adjustment_id,
        StockAdjustment.is_deleted == False
    ).first()

    if not adjustment:
        raise HTTPException(status_code=404, detail="Stock adjustment not found")

    # Only allow deletion if adjustment is in draft status
    if adjustment.status_adjustment != StatusStockAdjustmentEnum.DRAFT:
        raise HTTPException(
            status_code=400,
            detail="Only draft adjustments can be deleted. Finalized adjustments cannot be deleted."
        )

    try:
        no_adj = adjustment.no_adjustment

        # Delete adjustment items first (due to foreign key constraints)
        for item in adjustment.stock_adjustment_items:
            db.delete(item)

        # Soft delete the main adjustment record
        adjustment.is_deleted = True
        adjustment.deleted_at = datetime.now()

        # Log audit
        audit_service.default_log(
            entity_id=adjustment.id,
            entity_type=AuditEntityEnum.STOCK_ADJUSTMENT,
            description=f"Stock Adjustment {no_adj} dihapus",
            user_name=user_name
        )

        db.commit()

        return {"message": "Stock adjustment deleted successfully"}

    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error deleting stock adjustment: {str(e)}")