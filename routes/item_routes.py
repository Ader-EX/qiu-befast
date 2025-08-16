from datetime import datetime
from typing import Any, Dict, List, Literal, Optional
from fastapi import APIRouter, Depends, Form, Request, UploadFile, File
from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload
from starlette.exceptions import HTTPException
import shutil
import os
import uuid
from starlette.responses import FileResponse

from models.Item import Item
from database import get_db
from models.AllAttachment import AllAttachment,ParentType
from schemas.CategorySchemas import CategoryOut
from schemas.ItemSchema import ItemResponse, ItemTypeEnum, AttachmentResponse
from schemas.PaginatedResponseSchemas import PaginatedResponse
from schemas.SatuanSchemas import SatuanOut
from schemas.VendorSchemas import VendorOut
from utils import generate_unique_record_code, soft_delete_record

router = APIRouter()

NEXT_PUBLIC_UPLOAD_DIR = os.getenv("UPLOAD_DIR" ,default="uploads/items")
os.makedirs(NEXT_PUBLIC_UPLOAD_DIR, exist_ok=True)


def get_item_prefix(item_type: ItemTypeEnum) -> str:
    match item_type:
        case ItemTypeEnum.FINISH_GOOD:
            return "FG"
        case ItemTypeEnum.RAW_MATERIAL:
            return "RAW"
        case ItemTypeEnum.SERVICE:
            return "SERVICE"
        case _:
            raise ValueError(f"Unsupported item type: {item_type}")

@router.post("", response_model=ItemResponse)
async def create_item(
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
        images: List[UploadFile] = File(default=[]),
        db: Session = Depends(get_db)
):
    # Validate max 3 images
    if len(images) > 3:
        raise HTTPException(status_code=400, detail="Maximum 3 images allowed")
    pattern = get_item_prefix(type)
    # Check if SKU exists
    existing_item = db.query(Item).filter(Item.sku == sku).first()
    if existing_item:
        if existing_item.is_deleted:
            existing_item.type = type
            existing_item.code =  generate_unique_record_code(db,Item,pattern)
            existing_item.name = name
            existing_item.total_item = total_item
            existing_item.price = price
            existing_item.is_active = is_active
            existing_item.category_one = category_one
            existing_item.category_two = category_two
            existing_item.satuan_id = satuan_id
            existing_item.vendor_id = vendor_id
            existing_item.is_deleted = False
            existing_item.deleted_at = None
            db.commit()
            db.refresh(existing_item)
            return existing_item
        else:
            raise HTTPException(status_code=400, detail="SKU already exists")

    try:
        # Create new item
        db_item = Item(
            type=type,
            name=name,
            code =  generate_unique_record_code(db,Item,pattern),
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

                # Save to VPS
                vps_file_path = os.path.join(NEXT_PUBLIC_UPLOAD_DIR, unique_filename)
                with open(vps_file_path, "wb") as buffer:
                    shutil.copyfileobj(image.file, buffer)

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
        db.refresh(db_item)

        return db_item

    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error creating item: {str(e)}")



@router.get("", response_model=PaginatedResponse[ItemResponse])
def get_items(
        request: Request,
        db: Session = Depends(get_db),
        page: int = 1,
        rowsPerPage: int = 5,
        search_key: Optional[str] = None,
        vendor: Optional[str] = None,
        item_type: Optional[ItemTypeEnum] = None,
        is_active: Optional[bool] = None,
        sortBy: Optional[Literal["name", "price", "sku", "created_at"]] = None,
        sortOrder: Optional[Literal["asc", "desc"]] = "asc",
):

    query = db.query(Item).options(
        joinedload(Item.category_one_rel),
        joinedload(Item.category_two_rel),
        joinedload(Item.satuan_rel),
        joinedload(Item.vendor_rel),
        joinedload(Item.attachments)
    ).filter(Item.is_deleted == False)

    # Apply filters
    if search_key:
        query = query.filter(or_(
            Item.name.ilike(f"%{search_key}%"),
            Item.sku.ilike(f"%{search_key}%")
        ))

    if vendor and vendor != "all":
        query = query.filter(Item.vendor_id == vendor)
        
    if item_type:
        query = query.filter(Item.type == item_type)

    if is_active is not None:
        query = query.filter(Item.is_active == is_active)
    
    if sortBy:
        sort_column = getattr(Item, sortBy)
        if sortOrder == "desc":
            query = query.order_by(sort_column.desc())
        else:
            query = query.order_by(sort_column.asc())
        

    total_count = query.count()

    paginated_data = (
        query.offset((page - 1) * rowsPerPage)
        .limit(rowsPerPage)
        .all()
    )

    items_out = []
    for item in paginated_data:
        items_out.append(construct_item_response(item, request))
    
    return {
        "data": items_out,
        "total": total_count,
    }



@router.get("/{item_id}", response_model=ItemResponse)
def get_item(item_id: int, db: Session = Depends(get_db)):

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
        request: Request,
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
        vendor_id: str = Form(...),
        images: List[UploadFile] = File(default=[]),  # Changed from new_images to images
        db: Session = Depends(get_db)
):
    db_item = db.query(Item).filter(Item.id == item_id).first()
    if not db_item:
        raise HTTPException(status_code=404, detail="Item not found")

    # Check if SKU is unique (excluding current item)
    existing_item = db.query(Item).filter(Item.sku == sku, Item.id != item_id).first()
    if existing_item:
        raise HTTPException(status_code=400, detail="SKU already exists")

    try:
        # Update item fields
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

        # Handle images: if new images are provided, replace all existing ones
        if images and any(img.filename for img in images):
            # Validate image count
            if len(images) > 3:
                raise HTTPException(
                    status_code=400,
                    detail=f"Maximum 3 images allowed. You provided {len(images)}"
                )

            # Remove all existing images
            existing_attachments = db.query(AllAttachment).filter(
                AllAttachment.item_id == item_id
            ).all()

            for attachment in existing_attachments:
                file_path = attachment.file_path.replace("\\", "/")
                if os.path.exists(file_path):
                    os.remove(file_path)
                db.delete(attachment)

            # Add new images
            for image in images:
                if image.filename:
                    ext = os.path.splitext(image.filename)[1].lower()
                    unique_filename = f"{uuid.uuid4()}{ext}"
                    save_path = os.path.join(NEXT_PUBLIC_UPLOAD_DIR, unique_filename)
                    save_path = save_path.replace("\\", "/")

                    # Save to disk
                    with open(save_path, "wb") as buffer:
                        shutil.copyfileobj(image.file, buffer)

                    # Save DB record
                    attachment = AllAttachment(
                        parent_type=ParentType.ITEMS,
                        item_id=db_item.id,
                        filename=image.filename,
                        file_path=save_path,
                        file_size=os.path.getsize(save_path),
                        mime_type=image.content_type,
                        created_at=datetime.now()
                    )
                    db.add(attachment)

        db.commit()
        db.refresh(db_item)

        # Reload the item with relationships for the response
        updated_item = db.query(Item).options(
            joinedload(Item.category_one_rel),
            joinedload(Item.category_two_rel),
            joinedload(Item.satuan_rel),
            joinedload(Item.vendor_rel),
            joinedload(Item.attachments)
        ).filter(Item.id == item_id).first()

        return construct_item_response(updated_item, request)

    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error updating item: {str(e)}")

@router.delete("/{item_id}")
def delete_item(item_id: int, db: Session = Depends(get_db)):
    db_item = db.query(Item).filter(Item.id == item_id).first()
    if not db_item:
        raise HTTPException(status_code=404, detail="Item not found")

    try:
        # Physically delete all attachments and DB rows
        for attachment in db_item.attachments:
            file_path = attachment.file_path.replace("\\", "/")

            if os.path.exists(file_path):
                os.remove(file_path)
                print(f"Deleted file: {file_path}")
            else:
                print(f"File not found (skipped): {file_path}")

            db.delete(attachment)
        soft_delete_record(db,Item, item_id)

        db.commit()

        return {"message": f"Item {item_id} soft deleted successfully (attachments removed)"}

    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error deleting item: {str(e)}")


@router.get("/{item_id}/images/{attachment_id}")
def get_item_image(item_id: int, attachment_id: int, db: Session = Depends(get_db)):

    attachment = db.query(AllAttachment).filter(
        AllAttachment.id == attachment_id,
        AllAttachment.item_id == item_id,
        AllAttachment.parent_type == ParentType.ITEMS,
        AllAttachment.is_active == True
    ).first()

    if not attachment:
        raise HTTPException(status_code=404, detail="Image not found")

    if not os.path.exists(attachment.file_path):
        local_path = attachment.file_path.replace(NEXT_PUBLIC_UPLOAD_DIR)
        if os.path.exists(local_path):
            return FileResponse(local_path, media_type=attachment.mime_type)
        else:
            raise HTTPException(status_code=404, detail="Image file not found")

    return FileResponse(attachment.file_path, media_type=attachment.mime_type)

@router.post("/bulk-sync")
def sync_items_to_vps(db: Session = Depends(get_db)):
    try:
        synced_count = 0
        attachments = db.query(AllAttachment).filter(
            AllAttachment.parent_type == ParentType.ITEMS,
            AllAttachment.is_active == True
        ).all()

        for attachment in attachments:
            local_path = attachment.file_path.replace(NEXT_PUBLIC_UPLOAD_DIR)

            if not os.path.exists(attachment.file_path) and os.path.exists(local_path):
                os.makedirs(os.path.dirname(attachment.file_path), exist_ok=True)
                shutil.copy2(local_path, attachment.file_path)
                synced_count += 1

        return {"message": f"Synced {synced_count} files to VPS"}

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Sync error: {str(e)}")

@router.get("/stats/summary")
def get_items_stats(db: Session = Depends(get_db)):


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
    
    

def construct_item_response(item: Item, request: Request) -> Dict[str, Any]:
    """Helper function to construct item response with URLs"""
    static_url = os.environ.get("BASE_URL", "http://localhost:8000/static")

    enriched_attachments = []
    for att in item.attachments:
        clean_path = att.file_path.replace("\\", "/").replace("uploads/", "")
        enriched_attachments.append({
            "id": att.id,
            "filename": att.filename,
            "file_path": att.file_path,
            "file_size": att.file_size,
            "mime_type": att.mime_type,
            "created_at": att.created_at,
            "url": f"{static_url}/{clean_path}"
        })
    
    # Create response dict
    return {
        "id": item.id,
        "type": item.type,
        "name": item.name,
        "sku": item.sku,
        "code" : item.code,
        "total_item": item.total_item,
        "price": item.price,
        "is_active": item.is_active,
        "created_at": getattr(item, 'created_at', None),
        "category_one_rel": CategoryOut.model_validate(item.category_one_rel).model_dump() if item.category_one_rel else None,
        "category_two_rel": CategoryOut.model_validate(item.category_two_rel).model_dump() if item.category_two_rel else None,
        "satuan_rel": SatuanOut.model_validate(item.satuan_rel).model_dump() if item.satuan_rel else None,
        "vendor_rel": VendorOut.model_validate(item.vendor_rel).model_dump() if item.vendor_rel else None,
        "attachments": enriched_attachments
    }