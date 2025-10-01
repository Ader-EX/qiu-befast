import os
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session, joinedload, selectinload
from sqlalchemy import and_, or_, func, cast, Integer
from typing import List, Optional
from datetime import datetime, date, time
from decimal import Decimal

from database import get_db
from models.AllAttachment import AllAttachment
from models.AuditTrail import AuditEntityEnum
from models.StockAdjustment import StockAdjustment, StockAdjustmentItem, AdjustmentTypeEnum, StatusStockAdjustmentEnum
from models.Item import Item
from models.InventoryLedger import SourceTypeEnum
from schemas.PaginatedResponseSchemas import PaginatedResponse
from schemas.StockAdjustmentSchemas import (
    StockAdjustmentCreate,
    StockAdjustmentUpdate,
    StockAdjustmentResponse,
    StockAdjustmentListResponse
)
from services.audit_services import AuditService
from services.inventoryledger_services import InventoryService
from utils import generate_unique_record_number, get_current_user_name

router = APIRouter()


def adjust_item_stock(
        db: Session,
        item_id: int,
        qty: int,
        adjustment_type: AdjustmentTypeEnum,
        adjustment_price: Decimal,
        no_adj: str,
        trx_date: date,
        user_name: str
):
    """
    Helper function to adjust item stock and post to inventory ledger
    """
    audit_service = AuditService(db)
    inventory_service = InventoryService(db)

    item = db.query(Item).filter(Item.id == item_id, Item.is_deleted == False).first()
    if not item:
        raise HTTPException(status_code=404, detail=f"Item with ID {item_id} not found")

    old_stock = item.total_item

    # Determine source type based on adjustment type
    if adjustment_type == AdjustmentTypeEnum.OUT:
        source_type = SourceTypeEnum.OUT

        # Check sufficient stock
        if item.total_item < qty:
            raise HTTPException(
                status_code=400,
                detail=f"Insufficient stock for item {item.name}. Available: {item.total_item}, Required: {qty}"
            )

        # Post OUT to inventory ledger
        inventory_service.post_inventory_out(
            item_id=item_id,
            source_type=source_type,
            source_id=f"ADJUSTMENT:{no_adj}",
            qty=qty,
            trx_date=trx_date,
            reason_code=f"Stock Adjustment OUT: {no_adj}"
        )

        item.total_item -= qty
        action = "dikurangi"

    else:  # IN
        source_type = SourceTypeEnum.IN

        # Post IN to inventory ledger
        inventory_service.post_inventory_in(
            item_id=item_id,
            source_type=source_type,
            source_id=f"ADJUSTMENT:{no_adj}",
            qty=qty,
            unit_price=adjustment_price,
            trx_date=trx_date,
            reason_code=f"Stock Adjustment IN: {no_adj}"
        )

        item.total_item += qty
        action = "ditambahkan"

    new_stock = item.total_item

    # Log the stock change
    audit_service.default_log(
        entity_id=item.id,
        entity_type=AuditEntityEnum.ITEM,
        description=f"Stok item {item.name} {action} sebanyak {qty} (dari {old_stock} menjadi {new_stock}) - Adjustment: {no_adj}",
        user_name=user_name
    )

    db.flush()


def reverse_item_stock_adjustment(
        db: Session,
        item_id: int,
        qty: int,
        adjustment_type: AdjustmentTypeEnum,
        adjustment_price: Decimal,
        no_adj: str,
        trx_date: date,
        user_name: str
):
    """
    Helper function to reverse stock adjustment in inventory ledger
    """
    audit_service = AuditService(db)
    inventory_service = InventoryService(db)

    item = db.query(Item).filter(Item.id == item_id, Item.is_deleted == False).first()
    if not item:
        raise HTTPException(status_code=404, detail=f"Item with ID {item_id} not found")

    old_stock = item.total_item

    # Reverse the adjustment
    if adjustment_type == AdjustmentTypeEnum.OUT:
        # Original was OUT, so reverse with IN
        inventory_service.post_inventory_in(
            item_id=item_id,
            source_type=SourceTypeEnum.IN,
            source_id=f"REVERSAL_ADJUSTMENT:{no_adj}",
            qty=qty,
            unit_price=adjustment_price,
            trx_date=trx_date,
            reason_code=f"Reversal of Stock Adjustment OUT: {no_adj}"
        )

        item.total_item += qty
        action = "ditambahkan kembali"

    else:  # IN
        # Original was IN, so reverse with OUT
        if item.total_item < qty:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot reverse adjustment - insufficient stock for item {item.name}. Available: {item.total_item}, Required: {qty}"
            )

        inventory_service.post_inventory_out(
            item_id=item_id,
            source_type=SourceTypeEnum.OUT,
            source_id=f"REVERSAL_ADJUSTMENT:{no_adj}",
            qty=qty,
            trx_date=trx_date,
            reason_code=f"Reversal of Stock Adjustment IN: {no_adj}"
        )

        item.total_item -= qty
        action = "dikurangi kembali"

    new_stock = item.total_item

    # Log the reversal
    audit_service.default_log(
        entity_id=item.id,
        entity_type=AuditEntityEnum.ITEM,
        description=f"Stok item {item.name} {action} sebanyak {qty} (dari {old_stock} menjadi {new_stock}) - Reversal Adjustment: {no_adj}",
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
    total_price = Decimal("0")
    for item_data in adjustment_data.stock_adjustment_items:
        adj_item = StockAdjustmentItem(
            stock_adjustment_id=adjustment.id,
            **item_data.model_dump()
        )
        db.add(adj_item)
        total_qty += item_data.qty
        total_price += Decimal(str(item_data.adj_price))

    # Log audit
    audit_service.default_log(
        entity_id=adjustment.id,
        entity_type=AuditEntityEnum.STOCK_ADJUSTMENT,
        description=f"Penyesuaian {adjustment.no_adjustment} dibuat (Draft), tipe: {adjustment_data.adjustment_type}, total items: {total_qty}, total harga: {total_price}",
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
        joinedload(StockAdjustment.attachments),  
    ).filter(
        StockAdjustment.id == adjustment_id,
        StockAdjustment.is_deleted == False
    ).first()


    if not adjustment:
        raise HTTPException(status_code=404, detail="Stock adjustment not found")

    return adjustment


@router.get("/{pembelian_id}/download/{attachment_id}")
async def download_attachment(
        stock_adjustment_id: str,
        attachment_id: int,
        db: Session = Depends(get_db)
):
    """Download attachment file"""

    attachment = db.query(AllAttachment).filter(
        and_(
            AllAttachment.id == attachment_id,
            AllAttachment.stock_adjustment_id == stock_adjustment_id
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



@router.patch("/{adjustment_id}/rollback", status_code=status.HTTP_200_OK)
async def rollback_stock_adjustment(
        adjustment_id: int,
        db: Session = Depends(get_db),
        user_name: str = Depends(get_current_user_name)
):
    """
    Rolls back a Stock Adjustment from ACTIVE → DRAFT.
    Reverses the stock changes and inventory ledger entries.
    """
    audit_service = AuditService(db)

    adjustment = (
        db.query(StockAdjustment)
        .options(
            selectinload(StockAdjustment.stock_adjustment_items)
            .selectinload(StockAdjustmentItem.item_rel)
        )
        .filter(
            StockAdjustment.id == adjustment_id,
            StockAdjustment.is_deleted == False
        )
        .first()
    )

    if not adjustment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Stock adjustment not found"
        )

    if adjustment.status_adjustment != StatusStockAdjustmentEnum.ACTIVE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only ACTIVE stock adjustments can be rolled back"
        )

    # Reverse stock changes for each item
    for adj_item in adjustment.stock_adjustment_items:
        reverse_item_stock_adjustment(
            db=db,
            item_id=adj_item.item_id,
            qty=adj_item.qty,
            adjustment_type=adjustment.adjustment_type,
            adjustment_price=Decimal(str(adj_item.adj_price)),
            no_adj=adjustment.no_adjustment,
            trx_date=date.today(),  # Use today's date for reversal
            user_name=user_name
        )

    # Update status back to DRAFT
    adjustment.status_adjustment = StatusStockAdjustmentEnum.DRAFT

    # Audit log
    total_qty = sum(item.qty for item in adjustment.stock_adjustment_items)
    audit_service.default_log(
        entity_id=adjustment.id,
        entity_type=AuditEntityEnum.STOCK_ADJUSTMENT,
        description=(
            f"Penyesuaian {adjustment.no_adjustment} status diubah "
            f"dari ACTIVE → DRAFT, tipe: {adjustment.adjustment_type.value}"
        ),
        user_name=user_name
    )

    db.commit()
    db.refresh(adjustment)

    return {
        "message": "Stock adjustment rolled back successfully",
        "adjustment": adjustment
    }


@router.put("/{adjustment_id}/finalize")
def finalize_stock_adjustment(
        adjustment_id: int,
        db: Session = Depends(get_db),
        user_name: str = Depends(get_current_user_name)
):
    """Finalize stock adjustment and post to inventory ledger"""
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

    # Apply stock changes and post to inventory ledger
    for adj_item in adjustment.stock_adjustment_items:
        adjust_item_stock(
            db=db,
            item_id=adj_item.item_id,
            qty=adj_item.qty,
            adjustment_type=adjustment.adjustment_type,
            adjustment_price=Decimal(str(adj_item.adj_price)),
            no_adj=adjustment.no_adjustment,
            trx_date=adjustment.adjustment_date,
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
        description=f"Penyesuaian {adjustment.no_adjustment} status diubah: Draft → Aktif",
        user_name=user_name
    )

    db.commit()
    db.refresh(adjustment)

    return {"message": "Stock adjustment finalized successfully", "adjustment": adjustment}