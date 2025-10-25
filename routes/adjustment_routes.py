import os
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session, joinedload, selectinload
from sqlalchemy import and_, or_, func, cast, Integer
from typing import List, Optional
from datetime import datetime, date, time
from decimal import Decimal

from database import get_db
from models import InventoryLedger
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
from services.fifo_services import FifoService
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
        user_name: str,
        adjustment_item_id: int,
        warehouse_id: Optional[int] = None
):
    """
    Helper function to adjust item stock using FIFO
    """
    audit_service = AuditService(db)

    item = db.query(Item).filter(Item.id == item_id, Item.is_deleted == False).first()
    if not item:
        raise HTTPException(status_code=404, detail=f"Item with ID {item_id} not found")

    old_stock = item.total_item

    if adjustment_type == AdjustmentTypeEnum.OUT:
        # Consume from FIFO batches
        try:
            total_hpp, fifo_logs = FifoService.process_sale_fifo(
                db=db,
                invoice_id=f"ADJ-{no_adj}-{adjustment_item_id}",
                invoice_date=trx_date,
                item_id=item_id,
                qty_terjual=qty,
                harga_jual_per_unit=Decimal("0"),  # No sale price for adjustments
                warehouse_id=warehouse_id
            )
        except ValueError as e:
            raise HTTPException(
                status_code=400,
                detail=f"Insufficient stock for item {item.name}. {str(e)}"
            )

        item.total_item -= qty
        action = "dikurangi"

    else:  # IN
        # Create new FIFO batch
        FifoService.create_batch_from_purchase(
            source_id=item_id,
            source_type=SourceTypeEnum.IN,
            db=db,
            item_id=item_id,
            warehouse_id=warehouse_id,
            tanggal_masuk=trx_date,
            qty_masuk=qty,
            harga_beli=adjustment_price
        )

        item.total_item += qty
        action = "ditambahkan"

    new_stock = item.total_item

    audit_service.default_log(
        entity_id=item.id,
        entity_type=AuditEntityEnum.ITEM,
        description=f"Stok item {item.name} {action} sebanyak {qty} (dari {old_stock} menjadi {new_stock}) - Adjustment: {no_adj}",
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

@router.put("/{adjustment_id}", response_model=StockAdjustmentResponse, status_code=status.HTTP_200_OK)
def update_stock_adjustment(
    adjustment_id: int,
    payload: StockAdjustmentUpdate,
    db: Session = Depends(get_db),
    user_name: str = Depends(get_current_user_name),
):
    """
    Update a stock adjustment (only allowed in DRAFT).
    - Updates header fields: adjustment_date, warehouse_id, adjustment_type
    - Upserts items:
        * Existing items with an id -> updated
        * Items without id -> created
        * Existing items missing from payload -> deleted
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
        raise HTTPException(status_code=404, detail="Stock adjustment not found")

    if adjustment.status_adjustment != StatusStockAdjustmentEnum.DRAFT:
        raise HTTPException(
            status_code=400,
            detail="Only DRAFT stock adjustments can be updated. Roll back first if needed."
        )

    # Validate type if provided
    if payload.adjustment_type is not None:
        try:
            _ = AdjustmentTypeEnum(payload.adjustment_type)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid adjustment type. Must be IN or OUT")

    # Validate item list
    if not payload.stock_adjustment_items or len(payload.stock_adjustment_items) == 0:
        raise HTTPException(status_code=400, detail="Stock adjustment items are required")

    # Ensure all referenced Items exist
    item_ids = {it.item_id for it in payload.stock_adjustment_items}
    existing_items = {
        it.id: it for it in db.query(Item).filter(
            Item.id.in_(item_ids),
            Item.is_deleted == False
        ).all()
    }
    missing = item_ids - set(existing_items.keys())
    if missing:
        raise HTTPException(status_code=404, detail=f"Item(s) not found: {sorted(missing)}")

    # Map existing items
    current_items_by_id = {si.id: si for si in adjustment.stock_adjustment_items}

    # Track diffs for audit
    added, updated, removed = [], [], []

    incoming_ids = set()
    for item_in in payload.stock_adjustment_items:
        qty = int(item_in.qty)
        adj_price = int(item_in.adj_price)

        if getattr(item_in, "id", None):  # update
            incoming_ids.add(item_in.id)
            si = current_items_by_id.get(item_in.id)
            if not si or si.stock_adjustment_id != adjustment.id:
                raise HTTPException(
                    status_code=400,
                    detail=f"StockAdjustmentItem id {item_in.id} does not belong to this adjustment"
                )

            old_snapshot = {"item_id": si.item_id, "qty": si.qty, "adj_price": si.adj_price}
            si.item_id = item_in.item_id
            si.qty = qty
            si.adj_price = adj_price
            updated.append({"id": si.id, "from": old_snapshot,
                            "to": {"item_id": si.item_id, "qty": si.qty, "adj_price": si.adj_price}})
        else:  # create
            si_new = StockAdjustmentItem(
                stock_adjustment_id=adjustment.id,
                item_id=item_in.item_id,
                qty=qty,
                adj_price=adj_price,
            )
            db.add(si_new)
            db.flush()
            added.append({"id": si_new.id, "item_id": si_new.item_id, "qty": si_new.qty, "adj_price": si_new.adj_price})

    # delete missing
    for si_id, si in current_items_by_id.items():
        if si_id not in incoming_ids:
            removed.append({"id": si.id, "item_id": si.item_id, "qty": si.qty, "adj_price": si.adj_price})
            db.delete(si)

    # Update header fields if provided
    header_changes = []
    def _apply(field_name):
        if hasattr(payload, field_name):
            val = getattr(payload, field_name)
            if val is not None:
                old = getattr(adjustment, field_name)
                if old != val:
                    header_changes.append({"field": field_name, "from": old, "to": val})
                    setattr(adjustment, field_name, val)

    for field in ["adjustment_date", "warehouse_id", "adjustment_type"]:
        _apply(field)

    adjustment.updated_at = datetime.now()
    db.flush()

    # Recompute totals for audit context
    db.refresh(adjustment)
    total_qty = sum(int(si.qty or 0) for si in adjustment.stock_adjustment_items)
    total_price = sum(int(si.adj_price or 0) for si in adjustment.stock_adjustment_items)

    # Audit
    audit_parts = []
    if header_changes:
        audit_parts.append(
            "Header updated: " + ", ".join([f"{c['field']}: {c['from']} → {c['to']}" for c in header_changes])
        )
    if added:
        audit_parts.append(f"Items added: {len(added)}")
    if updated:
        audit_parts.append(f"Items updated: {len(updated)}")
    if removed:
        audit_parts.append(f"Items removed: {len(removed)}")

    audit_service.default_log(
        entity_id=adjustment.id,
        entity_type=AuditEntityEnum.STOCK_ADJUSTMENT,
        description=(
            f"Penyesuaian {adjustment.no_adjustment} diupdate (Draft). "
            f"{' | '.join(audit_parts) if audit_parts else 'No changes detected.'} "
            f"Total qty: {total_qty}, total harga: {total_price}"
        ),
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
@router.put("/{adjustment_id}/rollback", status_code=status.HTTP_200_OK)
async def rollback_stock_adjustment(
        adjustment_id: int,
        db: Session = Depends(get_db),
        user_name: str = Depends(get_current_user_name)
):
    """Rolls back a Stock Adjustment from ACTIVE → DRAFT using FIFO rollback"""
    from models.BatchStock import BatchStock, FifoLog
    
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
        raise HTTPException(status_code=404, detail="Stock adjustment not found")

    if adjustment.status_adjustment != StatusStockAdjustmentEnum.ACTIVE:
        raise HTTPException(
            status_code=400,
            detail="Only ACTIVE stock adjustments can be rolled back"
        )

    # Reverse stock changes for each item
    for adj_item in adjustment.stock_adjustment_items:
        item = db.query(Item).filter(Item.id == adj_item.item_id).first()

        if not item:
            raise HTTPException(
                status_code=404, 
                detail=f"Item {adj_item.item_id} telah dihapus, tidak bisa di-rollback"
            )

        old_stock = item.total_item

        if adjustment.adjustment_type == AdjustmentTypeEnum.OUT:
            # Original was OUT (consumed from batches via FIFO)
            # Reverse by rolling back the FifoLog entries
            invoice_id = f"ADJ-{adjustment.no_adjustment}-{adj_item.id}"
            
            try:
                FifoService.rollback_latest_sale(
                    db=db,
                    invoice_id=invoice_id,
                    invoice_date=adjustment.adjustment_date
                )
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e))

            item.total_item += adj_item.qty
            action = "ditambahkan kembali"

        else:  # IN
            # Original was IN (created a batch)
            # Delete the batch if it hasn't been used
            batch = db.query(BatchStock).filter(
                BatchStock.item_id == adj_item.item_id,
                BatchStock.warehouse_id == adjustment.warehouse_id,
                BatchStock.tanggal_masuk == adjustment.adjustment_date,
                BatchStock.qty_masuk == adj_item.qty,
                BatchStock.harga_beli == adj_item.adj_price
            ).first()

            if not batch:
                raise HTTPException(
                    status_code=404,
                    detail=f"Batch not found for item {item.name}"
                )

            if batch.qty_keluar > 0:
                raise HTTPException(
                    status_code=400,
                    detail=f"Cannot rollback - batch for {item.name} has been used in sales (qty_keluar: {batch.qty_keluar})"
                )

            # Safe to delete
            db.delete(batch)
            item.total_item -= adj_item.qty
            action = "dikurangi kembali"

        new_stock = item.total_item

        # Log the reversal
        audit_service.default_log(
            entity_id=item.id,
            entity_type=AuditEntityEnum.ITEM,
            description=f"Stok item {item.name} {action} sebanyak {adj_item.qty} (dari {old_stock} menjadi {new_stock}) - Rollback: {adjustment.no_adjustment}",
            user_name=user_name
        )

    # Update status back to DRAFT
    adjustment.status_adjustment = StatusStockAdjustmentEnum.DRAFT

    # Audit log
    audit_service.default_log(
        entity_id=adjustment.id,
        entity_type=AuditEntityEnum.STOCK_ADJUSTMENT,
        description=f"Penyesuaian {adjustment.no_adjustment} status diubah dari ACTIVE → DRAFT",
        user_name=user_name
    )

    db.commit()
    db.refresh(adjustment)

    return {
        "message": "Stock adjustment rolled back successfully",
        "adjustment": adjustment
    }

@router.delete("/{adjustment_id}", status_code=status.HTTP_200_OK)
def delete_stock_adjustment(
    adjustment_id: int,
    db: Session = Depends(get_db),
    user_name: str = Depends(get_current_user_name)
):
    """
    Delete a stock adjustment.
    - DRAFT: Can be deleted directly (soft delete)
    - ACTIVE: Must be rolled back first, then inventory entries are reversed
    """
    audit_service = AuditService(db)
    
    # Fetch adjustment with items
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
        raise HTTPException(status_code=404, detail="Stock adjustment not found")

    adjustment_number = adjustment.no_adjustment
    adjustment_status = adjustment.status_adjustment
    total_items = len(adjustment.stock_adjustment_items)

    # Handle ACTIVE adjustments - must reverse stock changes first
    skipped_items = []
    if adjustment.status_adjustment == StatusStockAdjustmentEnum.ACTIVE:
        from models.BatchStock import BatchStock, FifoLog
        
        # Reverse stock changes for each item
        for adj_item in adjustment.stock_adjustment_items:
            item = db.query(Item).filter(Item.id == adj_item.item_id).first()

            if not item:
                # Item was deleted - skip reversal but log it
                skipped_items.append({
                    "item_id": adj_item.item_id,
                    "qty": adj_item.qty,
                    "reason": "Item sudah dihapus"
                })
                audit_service.default_log(
                    entity_id=adjustment.id,
                    entity_type=AuditEntityEnum.STOCK_ADJUSTMENT,
                    description=f"Item ID {adj_item.item_id} dilewati saat penghapusan {adjustment.no_adjustment} (item sudah dihapus)",
                    user_name=user_name
                )
                continue

            old_stock = item.total_item

            # Reverse the adjustment
            if adjustment.adjustment_type == AdjustmentTypeEnum.OUT:
                # Original was OUT, reverse by rolling back FIFO
                invoice_id = f"ADJ-{adjustment.no_adjustment}-{adj_item.id}"
                
                try:
                    FifoService.rollback_latest_sale(
                        db=db,
                        invoice_id=invoice_id,
                        invoice_date=adjustment.adjustment_date
                    )
                    item.total_item += adj_item.qty
                    action = "dikembalikan"
                except ValueError as e:
                    # This sale wasn't the latest - can't rollback
                    raise HTTPException(
                        status_code=400,
                        detail=f"Cannot delete - adjustment for {item.name} is not the latest transaction. Rollback newer transactions first."
                    )

            else:  # IN
                # Original was IN, delete the batch
                batch = db.query(BatchStock).filter(
                    BatchStock.item_id == adj_item.item_id,
                    BatchStock.warehouse_id == adjustment.warehouse_id,
                    BatchStock.tanggal_masuk == adjustment.adjustment_date,
                    BatchStock.qty_masuk == adj_item.qty,
                    BatchStock.harga_beli == adj_item.adj_price
                ).first()

                if not batch:
                    skipped_items.append({
                        "item_id": adj_item.item_id,
                        "qty": adj_item.qty,
                        "reason": "Batch not found"
                    })
                    continue

                if batch.qty_keluar > 0:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Cannot delete - batch for {item.name} has been used (qty_keluar: {batch.qty_keluar})"
                    )

                db.delete(batch)
                item.total_item -= adj_item.qty
                action = "dikurangi"

            new_stock = item.total_item

            # Log the reversal
            audit_service.default_log(
                entity_id=item.id,
                entity_type=AuditEntityEnum.ITEM,
                description=f"Stok item {item.name} {action} sebanyak {adj_item.qty} (dari {old_stock} menjadi {new_stock}) - Penghapusan Adjustment: {adjustment.no_adjustment}",
                user_name=user_name
            )

    # Soft delete the adjustment (cascade will handle items and attachments)
    adjustment.is_deleted = True
    adjustment.deleted_at = datetime.now()

    # Log deletion
    audit_service.default_log(
        entity_id=adjustment.id,
        entity_type=AuditEntityEnum.STOCK_ADJUSTMENT,
        description=f"Penyesuaian {adjustment_number} dihapus (Status: {adjustment_status.value}, Total Items: {total_items})",
        user_name=user_name
    )

    db.commit()

    response = {
        "message": "Stock adjustment deleted successfully",
        "no_adjustment": adjustment_number,
        "status": adjustment_status.value,
        "items_affected": total_items
    }
    
    if skipped_items:
        response["skipped_items"] = skipped_items
        response["warning"] = f"{len(skipped_items)} item(s) sudah dihapus, stok tidak dapat dikembalikan"
    
    return response

@router.put("/{adjustment_id}/finalize")
def finalize_stock_adjustment(
        adjustment_id: int,
        db: Session = Depends(get_db),
        user_name: str = Depends(get_current_user_name)
):
    """Finalize stock adjustment and post to FIFO batches"""
    from models.BatchStock import BatchStock
    from sqlalchemy import func, and_
    
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

    # 1) Validate ALL items first - collect all errors
    validation_errors = []
    for adj_item in adjustment.stock_adjustment_items:
        try:
            if not adj_item.item_id:
                item_name = adj_item.item_rel.name if adj_item.item_rel else "Unknown"
                validation_errors.append(f"{item_name}: Item ID is missing")
                continue
            
            # If it's OUT, check if stock is sufficient using FIFO batches
            if adjustment.adjustment_type == AdjustmentTypeEnum.OUT:
                # Calculate total available stock from open batches
                available_query = db.query(
                    func.sum(BatchStock.sisa_qty).label('total_available')
                ).filter(
                    and_(
                        BatchStock.item_id == adj_item.item_id,
                        BatchStock.is_open == True,
                        BatchStock.sisa_qty > 0
                    )
                )
                
                # Filter by warehouse if specified
                if adjustment.warehouse_id:
                    available_query = available_query.filter(
                        BatchStock.warehouse_id == adjustment.warehouse_id
                    )
                
                result = available_query.scalar()
                available = result if result else 0
                
                if available < adj_item.qty:
                    item_name = adj_item.item_rel.name if adj_item.item_rel else f"ID {adj_item.item_id}"
                    validation_errors.append(
                        f"{item_name}: Stock tidak mencukupi. Tersedia: {available}, Dibutuhkan: {adj_item.qty}"
                    )
                    
        except Exception as e:
            item_name = adj_item.item_rel.name if adj_item.item_rel else f"ID {adj_item.item_id}"
            validation_errors.append(f"{item_name}: {str(e)}")
    
    # If ANY validation failed, raise error WITHOUT making any changes
    if validation_errors:
        raise HTTPException(
            status_code=400, 
            detail=f"Tidak dapat finalisasi adjustment - ada masalah: {'; '.join(validation_errors)}"
        )

    # 2) NOW safe to apply stock changes - we know ALL items are valid
    for adj_item in adjustment.stock_adjustment_items:
        adjust_item_stock(
            db=db,
            item_id=adj_item.item_id,
            qty=adj_item.qty,
            adjustment_type=adjustment.adjustment_type,
            adjustment_price=Decimal(str(adj_item.adj_price)),
            no_adj=adjustment.no_adjustment,
            trx_date=adjustment.adjustment_date,
            user_name=user_name,
            adjustment_item_id=adj_item.id,
            warehouse_id=adjustment.warehouse_id
        )

    # 3) Update status to ACTIVE
    adjustment.status_adjustment = StatusStockAdjustmentEnum.ACTIVE
    adjustment.updated_at = datetime.now()

    audit_service.default_log(
        entity_id=adjustment.id,
        entity_type=AuditEntityEnum.STOCK_ADJUSTMENT,
        description=f"Penyesuaian {adjustment.no_adjustment} status diubah: Draft → Aktif",
        user_name=user_name
    )

    db.commit()
    db.refresh(adjustment)

    return {"message": "Stock adjustment finalized successfully", "adjustment": adjustment}