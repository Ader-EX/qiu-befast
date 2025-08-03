from datetime import datetime
from typing import List, Optional
from fastapi import APIRouter, Depends, Form, UploadFile, File
from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload
from starlette import status
from starlette.exceptions import HTTPException
import shutil
import os
import uuid
from starlette.responses import FileResponse

from models.Item import Item
from database import get_db
from models.AllAttachment import AllAttachment,ParentType
from schemas.ItemSchema import ItemResponse, ItemTypeEnum, AttachmentResponse
from schemas.PaginatedResponseSchemas import PaginatedResponse
from schemas.SatuanSchemas import SatuanOut
from schemas.TopSchemas import TopOut
from schemas.VendorSchemas import VendorOut


router = APIRouter()

NEXT_PUBLIC_UPLOAD_DIR = os.getenv("UPLOAD_DIR" ,default="uploads/items")
os.makedirs(NEXT_PUBLIC_UPLOAD_DIR, exist_ok=True)

@router.post("", response_model=ItemResponse)
async def create_item(
        # Item data
        type: ItemTypeEnum = Form(...),
        name: str = Form(...),
        sku: str = Form(...),
        total_item: int = Form(0),
        price: float = Form(...),
        is_active: bool = Form(True),
        category_one: Optional[int] = Form(None),
        category_two: Optional[int] = Form(None),
        satuan_id: int = Form(...),
        vendor_id: str = Form(...),
        # Images (max 3)
        images: List[UploadFile] = File(default=[]),
        db: Session = Depends(get_db)
):


    # Validate max 3 images
    if len(images) > 3:
        raise HTTPException(status_code=400, detail="Maximum 3 images allowed")

    # Check if SKU already exists
    existing_item = db.query(Item).filter(Item.sku == sku).first()
    if existing_item:
        raise HTTPException(status_code=400, detail="SKU already exists")

    try:
        # Create item
        db_item = Item(
            type=type,
            name=name,
            sku=sku,
            total_item=total_item,
            price=price,
            is_active=is_active,
            category_one=category_one,
            category_two=category_two,
            satuan_id=satuan_id,
            vendor_id=vendor_id
        )

        db.add(db_item)
        db.commit()
        db.refresh(db_item)

        # Handle image uploads
        attachments = []
        for image in images:
            if image.filename:
                # Generate unique filename
                file_extension = os.path.splitext(image.filename)[1]
                unique_filename = f"{uuid.uuid4()}{file_extension}"

                # Save to VPS (production path)
                vps_file_path = os.path.join(NEXT_PUBLIC_UPLOAD_DIR, unique_filename)
                with open(vps_file_path, "wb") as buffer:
                    shutil.copyfileobj(image.file, buffer)

                # local_file_path = os.path.join(NEXT_PUBLIC_LOCAL_UPLOAD_DIR, unique_filename)
                image.file.seek(0)  # Reset file pointer
                # with open(local_file_path, "wb") as buffer:
                #     shutil.copyfileobj(image.file, buffer)

                attachment = AllAttachment(
                    parent_type=ParentType.ITEMS,
                    item_id=db_item.id,
                    filename=image.filename,
                    file_path=vps_file_path,
                    file_size=os.path.getsize(vps_file_path),
                    mime_type=image.content_type,
                    
                    created_at=datetime.now()
                )

                db.add(attachment)
                attachments.append(attachment)

        db.commit()

        # Refresh item with attachments
        db.refresh(db_item)

        print(f"Saving to: {NEXT_PUBLIC_UPLOAD_DIR}")
        item_dict = {
            "id": db_item.id,
            "type": db_item.type,
            "name": db_item.name,
            "sku": db_item.sku,
            "total_item": db_item.total_item,
            "price": float(db_item.price),
            "is_active": db_item.is_active,
            "category_one": db_item.category_one,
            "category_two": db_item.category_two,
            "satuan_id": db_item.satuan_id,
            "vendor_id": db_item.vendor_id,
            "attachments": [
                {
                    "id": att.id,
                    "filename": att.filename,
                    "file_path": att.file_path,
                    "file_size": att.file_size,
                    "mime_type": att.mime_type,
                    "created_at": att.created_at,
                } for att in db_item.attachments
            ]
        }

        return item_dict

    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error creating item: {str(e)}")


@router.get("", response_model=PaginatedResponse[ItemResponse])
def get_items(
        db: Session = Depends(get_db),
        page: int = 1,
        rowsPerPage: int = 5,
        search_key: Optional[str] = None,
        item_type: Optional[ItemTypeEnum] = None,
        is_active: Optional[bool] = None,
):
    """Get all items with filtering and pagination"""

    query = db.query(Item).options(
        joinedload(Item.category_one_rel),
        joinedload(Item.category_two_rel),
        joinedload(Item.satuan_rel),
        joinedload(Item.vendor_rel),
        joinedload(Item.attachments)
    )

    # Apply filters
    if search_key:
        query = query.filter(or_(
            Item.name.ilike(f"%{search_key}%"),
            Item.sku.ilike(f"%{search_key}%")
        ))

    if item_type:
        query = query.filter(Item.type == item_type)

    if is_active is not None:
        query = query.filter(Item.is_active == is_active)
        
    
    total_data  = query.count()

    total_count = query.count()

    paginated_data = (
        query.offset((page - 1) * rowsPerPage)
        .limit(rowsPerPage)
        .all()
    )

    return {
        "data": paginated_data,
        "total": total_count,
    }

@router.get("/{item_id}", response_model=ItemResponse)
def get_item(item_id: int, db: Session = Depends(get_db)):
    """Get a specific item by ID"""

    item = db.query(Item).filter(Item.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    item_dict = {
        "id": item.id,
        "type": item.type,
        "name": item.name,
        "sku": item.sku,
        "total_item": item.total_item,
        "price": float(item.price),
        "is_active": item.is_active,
        "category_one": item.category_one,
        "category_two": item.category_two,
        "satuan_id": item.satuan_id,
        "vendor_id": item.vendor_id,
        "attachments": [
            {
                "id": att.id,
                "filename": att.filename,
                "file_path": att.file_path,
                "file_size": att.file_size,
                "mime_type": att.mime_type
            } for att in item.attachments if att.is_active
        ]
    }

    return item_dict

@router.put("/{item_id}", response_model=ItemResponse)
async def update_item(
        item_id: int,
        type: ItemTypeEnum = Form(...),
        name: str = Form(...),
        sku: str = Form(...),
        total_item: int = Form(0),
        price: float = Form(...),
        is_active: bool = Form(True),
        category_one: Optional[int] = Form(None),
        category_two: Optional[int] = Form(None),
        satuan_id: int = Form(...),
        vendor_id: int = Form(...),
        new_images: List[UploadFile] = File(default=[]),
        remove_image_ids: Optional[str] = Form(None),
        db: Session = Depends(get_db)
):


    # Get existing item
    db_item = db.query(Item).filter(Item.id == item_id).first()
    if not db_item:
        raise HTTPException(status_code=404, detail="Item not found")

    # Check if SKU is unique (excluding current item)
    existing_item = db.query(Item).filter(Item.sku == sku, Item.id != item_id).first()
    if existing_item:
        raise HTTPException(status_code=400, detail="SKU already exists")

    try:

        db_item.type = type
        db_item.name = name
        db_item.sku = sku
        db_item.total_item = total_item
        db_item.price = price
        db_item.is_active = is_active
        db_item.category_one = category_one
        db_item.category_two = category_two
        db_item.satuan_id = satuan_id
        db_item.vendor_id = vendor_id

        # Handle image removal
        if remove_image_ids:
            remove_ids = [int(id.strip()) for id in remove_image_ids.split(',') if id.strip()]
            for attachment_id in remove_ids:
                attachment = db.query(AllAttachment).filter(
                    AllAttachment.id == attachment_id,
                    AllAttachment.item_id == item_id
                ).first()
                if attachment:
                    # Remove files from both locations
                    if os.path.exists(attachment.file_path):
                        os.remove(attachment.file_path)

                    local_path = attachment.file_path.replace(NEXT_PUBLIC_UPLOAD_DIR)
                    if os.path.exists(local_path):
                        os.remove(local_path)

                    db.delete(attachment)

        # Check current image count after removal
        current_images = db.query(AllAttachment).filter(
            AllAttachment.item_id == item_id,
            AllAttachment.is_active == True
        ).count()

        # Validate new images don't exceed limit
        if current_images + len(new_images) > 3:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot add {len(new_images)} images. Current: {current_images}, Max: 3"
            )

        # Handle new image uploads
        for image in new_images:
            if image.filename:
                # Generate unique filename
                file_extension = os.path.splitext(image.filename)[1]
                unique_filename = f"{uuid.uuid4()}{file_extension}"

                # Save to VPS
                vps_file_path = os.path.join(NEXT_PUBLIC_UPLOAD_DIR, unique_filename)
                with open(vps_file_path, "wb") as buffer:
                    shutil.copyfileobj(image.file, buffer)

                # Save locally
                # local_file_path = os.path.join(NEXT_PUBLIC_LOCAL_UPLOAD_DIR, unique_filename)
                # image.file.seek(0)
                # with open(local_file_path, "wb") as buffer:
                #     shutil.copyfileobj(image.file, buffer)

                # Create attachment record
                attachment = AllAttachment(
                    parent_type=ParentType.ITEMS,
                    item_id=db_item.id,
                    filename=image.filename,
                    file_path=vps_file_path,
                    file_size=os.path.getsize(vps_file_path),
                    mime_type=image.content_type,
                    is_active=True,
                    created_at=datetime.now()
                )

                db.add(attachment)

        db.commit()
        db.refresh(db_item)

        # Format response
        item_dict = {
            "id": db_item.id,
            "type": db_item.type,
            "name": db_item.name,
            "sku": db_item.sku,
            "total_item": db_item.total_item,
            "price": float(db_item.price),
            "is_active": db_item.is_active,
            "category_one": db_item.category_one,
            "category_two": db_item.category_two,
            "satuan_id": db_item.satuan_id,
            "vendor_id": db_item.vendor_id,
            "attachments": [
                {
                    "id": att.id,
                    "filename": att.filename,
                    "file_path": att.file_path,
                    "file_size": att.file_size,
                    "mime_type": att.mime_type
                } for att in db_item.attachments if att.is_active
            ]
        }

        return item_dict

    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error updating item: {str(e)}")

@router.delete("/{item_id}")
def delete_item(item_id: int, db: Session = Depends(get_db)):


    db_item = db.query(Item).filter(Item.id == item_id).first()
    if not db_item:
        raise HTTPException(status_code=404, detail="Item not found")

    try:
        # Delete all associated images
        for attachment in db_item.attachments:
            # Remove files from both locations
            if os.path.exists(attachment.file_path):
                os.remove(attachment.file_path)

            local_path = attachment.file_path.replace(NEXT_PUBLIC_UPLOAD_DIR)
            if os.path.exists(local_path):
                os.remove(local_path)

        # Delete item (cascades to attachments)
        db.delete(db_item)
        db.commit()

        return {"message": f"Item {item_id} deleted successfully"}

    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error deleting item: {str(e)}")

@router.get("/{item_id}/images/{attachment_id}")
def get_item_image(item_id: int, attachment_id: int, db: Session = Depends(get_db)):
    """Get a specific image for an item"""

    attachment = db.query(AllAttachment).filter(
        AllAttachment.id == attachment_id,
        AllAttachment.item_id == item_id,
        AllAttachment.parent_type == ParentType.ITEMS,
        AllAttachment.is_active == True
    ).first()

    if not attachment:
        raise HTTPException(status_code=404, detail="Image not found")

    if not os.path.exists(attachment.file_path):
        # Try local backup
        local_path = attachment.file_path.replace(NEXT_PUBLIC_UPLOAD_DIR)
        if os.path.exists(local_path):
            return FileResponse(local_path, media_type=attachment.mime_type)
        else:
            raise HTTPException(status_code=404, detail="Image file not found")

    return FileResponse(attachment.file_path, media_type=attachment.mime_type)

@router.post("/bulk-sync")
def sync_items_to_vps(db: Session = Depends(get_db)):
    """Sync all local images to VPS location (utility endpoint)"""

    try:
        synced_count = 0
        attachments = db.query(AllAttachment).filter(
            AllAttachment.parent_type == ParentType.ITEMS,
            AllAttachment.is_active == True
        ).all()

        for attachment in attachments:
            local_path = attachment.file_path.replace(NEXT_PUBLIC_UPLOAD_DIR)

            # If VPS file doesn't exist but local does, copy it
            if not os.path.exists(attachment.file_path) and os.path.exists(local_path):
                os.makedirs(os.path.dirname(attachment.file_path), exist_ok=True)
                shutil.copy2(local_path, attachment.file_path)
                synced_count += 1

        return {"message": f"Synced {synced_count} files to VPS"}

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Sync error: {str(e)}")

@router.get("/stats/summary")
def get_items_stats(db: Session = Depends(get_db)):
    """Get summary statistics for items"""

    total_items = db.query(Item).count()
    active_items = db.query(Item).filter(Item.is_active == True).count()
    inactive_items = total_items - active_items

    # Count by type
    type_counts = {}
    for item_type in ItemTypeEnum:
        count = db.query(Item).filter(Item.type == item_type).count()
        type_counts[item_type.value] = count

    # Total images
    total_images = db.query(AllAttachment).filter(
        AllAttachment.parent_type == ParentType.ITEMS,
        AllAttachment.is_active == True
    ).count()

    return {
        "total_items": total_items,
        "active_items": active_items,
        "inactive_items": inactive_items,
        "type_distribution": type_counts,
        "total_images": total_images
    }