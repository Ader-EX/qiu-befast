from datetime import datetime
from typing import Any, Dict, List, Literal, Optional
from fastapi import APIRouter, Depends, Form, Request, UploadFile, File
from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload
from starlette.exceptions import HTTPException
import shutil
import os
import uuid


from models.Item import Item
from database import get_db
from models.AllAttachment import AllAttachment, ParentType
from schemas.CategorySchemas import CategoryOut
from schemas.ItemSchema import ItemResponse, ItemTypeEnum
from schemas.PaginatedResponseSchemas import PaginatedResponse
from schemas.SatuanSchemas import SatuanOut

from utils import generate_unique_record_code, soft_delete_record

router = APIRouter()

NEXT_PUBLIC_UPLOAD_DIR = os.getenv("UPLOAD_DIR", default="uploads/items")
os.makedirs(NEXT_PUBLIC_UPLOAD_DIR, exist_ok=True)


def get_item_prefix(item_type: ItemTypeEnum) -> str:
    if item_type == ItemTypeEnum.FINISH_GOOD:
        return "FG"
    elif item_type == ItemTypeEnum.RAW_MATERIAL:
        return "RAW"
    elif item_type == ItemTypeEnum.SERVICE:
        return "SERVICE"
    else:
        raise ValueError(f"Unsupported item type: {item_type}")


@router.get("/{item_id}", response_model=ItemResponse)
def get_item_by_id(
        request: Request,
        item_id: int,
        db: Session = Depends(get_db),
):
    db_item = db.query(Item).options(
        joinedload(Item.category_one_rel),
        joinedload(Item.category_two_rel),
        joinedload(Item.satuan_rel),
        joinedload(Item.attachments),
    ).filter(Item.id == item_id, Item.is_deleted == False).first()

    if not db_item:
        raise HTTPException(status_code=404, detail="Item not found")

    return construct_item_response(db_item, request)

@router.post("", response_model=ItemResponse)
async def create_item(
        images: List[UploadFile] = File(default=[]),  # Move this FIRST
        type: ItemTypeEnum = Form(...),
        name: str = Form(...),
        sku: str = Form(...),
        total_item: int = Form(0),
        price: float = Form(...),
        is_active: bool = Form(True),
        category_one: Optional[int] = Form(None),
        category_two: Optional[int] = Form(None),
        satuan_id: int = Form(...),

        db: Session = Depends(get_db),
):
    if len(images) > 3:
        raise HTTPException(status_code=400, detail="Maximum 3 images allowed")

    pattern = get_item_prefix(type)

    # SKU validation
    existing_item = db.query(Item).filter(Item.sku == sku).first()
    if existing_item:
        if existing_item.is_deleted:
            existing_item.type = type
            existing_item.code = generate_unique_record_code(db, Item, pattern)
            existing_item.name = name
            existing_item.total_item = total_item
            existing_item.price = price
            existing_item.is_active = is_active
            existing_item.category_one = category_one
            existing_item.category_two = category_two
            existing_item.satuan_id = satuan_id

            existing_item.is_deleted = False
            existing_item.deleted_at = None
            db.commit()
            db.refresh(existing_item)
            return existing_item
        else:
            raise HTTPException(status_code=400, detail="SKU already exists")

    try:
        db_item = Item(
            type=type,
            name=name,
            code=generate_unique_record_code(db, Item, pattern),
            sku=sku,
            total_item=total_item,
            price=price,
            is_active=is_active,
            category_one=category_one,
            category_two=category_two,
            satuan_id=satuan_id,

        )

        db.add(db_item)
        db.commit()
        db.refresh(db_item)

        # Handle images
        for image in images:
            if image.filename:
                ext = os.path.splitext(image.filename)[1]
                unique_filename = f"{uuid.uuid4()}{ext}"
                save_path = os.path.join(NEXT_PUBLIC_UPLOAD_DIR, unique_filename)

                with open(save_path, "wb") as buffer:
                    shutil.copyfileobj(image.file, buffer)

                attachment = AllAttachment(
                    parent_type=ParentType.ITEMS,
                    item_id=db_item.id,
                    filename=image.filename,
                    file_path=save_path,
                    file_size=os.path.getsize(save_path),
                    mime_type=image.content_type,
                    created_at=datetime.now(),
                )
                db.add(attachment)

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
        item_type: Optional[ItemTypeEnum] = None,
        is_active: Optional[bool] = None,
        sortBy: Optional[Literal["name", "price", "sku", "created_at"]] = None,
        sortOrder: Optional[Literal["asc", "desc"]] = "asc",
):
    query = db.query(Item).options(
        joinedload(Item.category_one_rel),
        joinedload(Item.category_two_rel),
        joinedload(Item.satuan_rel),
        joinedload(Item.attachments),
    ).filter(Item.is_deleted == False)

    if search_key:
        query = query.filter(
            or_(
                Item.name.ilike(f"%{search_key}%"),
                Item.sku.ilike(f"%{search_key}%"),
            )
        )

    if item_type:
        query = query.filter(Item.type == item_type)

    if is_active is not None:
        query = query.filter(Item.is_active == is_active)

    if sortBy:
        sort_column = getattr(Item, sortBy)
        query = query.order_by(sort_column.desc() if sortOrder == "desc" else sort_column.asc())

    total_count = query.count()
    paginated_data = query.offset((page - 1) * rowsPerPage).limit(rowsPerPage).all()

    items_out = [construct_item_response(item, request) for item in paginated_data]

    return {"data": items_out, "total": total_count}


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

        images: List[UploadFile] = File(default=[]),
        db: Session = Depends(get_db),
):
    db_item = db.query(Item).filter(Item.id == item_id).first()
    if not db_item:
        raise HTTPException(status_code=404, detail="Item not found")

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


        # Handle images
        if images and any(img.filename for img in images):
            if len(images) > 3:
                raise HTTPException(status_code=400, detail="Maximum 3 images allowed")

            existing_attachments = db.query(AllAttachment).filter(AllAttachment.item_id == item_id).all()
            for attachment in existing_attachments:
                if os.path.exists(attachment.file_path):
                    os.remove(attachment.file_path)
                db.delete(attachment)

            for image in images:
                if image.filename:
                    ext = os.path.splitext(image.filename)[1]
                    unique_filename = f"{uuid.uuid4()}{ext}"
                    save_path = os.path.join(NEXT_PUBLIC_UPLOAD_DIR, unique_filename)

                    with open(save_path, "wb") as buffer:
                        shutil.copyfileobj(image.file, buffer)

                    attachment = AllAttachment(
                        parent_type=ParentType.ITEMS,
                        item_id=db_item.id,
                        filename=image.filename,
                        file_path=save_path,
                        file_size=os.path.getsize(save_path),
                        mime_type=image.content_type,
                        created_at=datetime.now(),
                    )
                    db.add(attachment)

        db.commit()
        db.refresh(db_item)

        return construct_item_response(db_item, request)

    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error updating item: {str(e)}")


@router.delete("/{item_id}")
def delete_item(item_id: int, db: Session = Depends(get_db)):
    db_item = db.query(Item).filter(Item.id == item_id).first()
    if not db_item:
        raise HTTPException(status_code=404, detail="Item not found")

    try:
        for attachment in db_item.attachments:
            if os.path.exists(attachment.file_path):
                os.remove(attachment.file_path)
            db.delete(attachment)

        soft_delete_record(db, Item, item_id)

        db.commit()
        return {"message": f"Item {item_id} soft deleted successfully (attachments removed)"}

    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error deleting item: {str(e)}")


def construct_item_response(item: Item, request: Request) -> Dict[str, Any]:
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
            "url": f"{static_url}/{clean_path}",
        })

    return {
        "id": item.id,
        "type": item.type,
        "name": item.name,
        "sku": item.sku,
        "code": item.code,
        "total_item": item.total_item,
        "price": item.price,
        "is_active": item.is_active,

        "created_at": getattr(item, "created_at", None),
        "category_one_rel": CategoryOut.model_validate(item.category_one_rel).model_dump() if item.category_one_rel else None,
        "category_two_rel": CategoryOut.model_validate(item.category_two_rel).model_dump() if item.category_two_rel else None,
        "satuan_rel": SatuanOut.model_validate(item.satuan_rel).model_dump() if item.satuan_rel else None,
        "attachments": enriched_attachments,
    }
