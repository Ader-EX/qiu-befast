from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Literal, Optional

import pandas as pd
from fastapi import APIRouter, Depends, Form, Request, UploadFile, File, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload
from starlette.exceptions import HTTPException
import shutil
import os
import uuid


from models.Item import Item
from database import get_db
from models.AllAttachment import AllAttachment, ParentType
from routes.category_routes import _build_categories_lookup
from routes.satuan_routes import _build_satuans_lookup
from schemas.CategorySchemas import CategoryOut
from schemas.ItemSchema import ItemResponse, ItemTypeEnum
from schemas.PaginatedResponseSchemas import PaginatedResponse
from schemas.SatuanSchemas import SatuanOut
import pandas as pd
import io
from typing import List, Dict, Any, Optional
from pydantic import BaseModel
from decimal import Decimal

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




class ImportResult(BaseModel):
    total_processed: int
    successful_imports: int
    failed_imports: int
    errors: List[Dict[str, Any]]
    warnings: List[Dict[str, Any]]

class ImportOptions(BaseModel):
    skip_on_error: bool = True
    update_existing: bool = False
    default_item_type: ItemTypeEnum = ItemTypeEnum.FINISH_GOOD

def _create_new_item(db: Session, item_data: Dict[str, Any]):
    """Create a new item."""
    new_item = Item(**item_data)
    db.add(new_item)
    db.flush()

def _update_existing_item(db: Session, item_data: Dict[str, Any], existing_item_id: int):
    """Update an existing item."""
    item = db.query(Item).filter(Item.id == existing_item_id).first()
    if item:
        for key, value in item_data.items():
            if hasattr(item, key):
                setattr(item, key, value)

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
        raise HTTPException(status_code=404, detail="Item tidak ditemukan")

    return construct_item_response(db_item, request)

@router.post("", response_model=ItemResponse)
async def create_item(
        images: List[UploadFile] = File(default=[]),
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
        raise HTTPException(status_code=400, detail=f"{str(e)}")

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



@router.post("/import-excel", response_model=ImportResult)
async def import_items_from_excel(
        file: UploadFile = File(...),
        skip_on_error: bool = Query(True, description="Skip rows with errors instead of failing completely"),
        update_existing: bool = Query(False, description="Update existing items if SKU already exists"),
        default_item_type: ItemTypeEnum = Query(ItemTypeEnum.FINISH_GOOD, description="Default item type if not specified"),
        db: Session = Depends(get_db)
):
    """
    Import items from Excel/CSV file using the template format.

    Expected columns:
    - Item Code (optional)
    - Nama Item (required)
    - SKU (required, unique)
    - Kategori 1 (optional, by name)
    - Kategori 2 (optional, by name)
    - Jumlah Unit (optional, defaults to 0)
    - Harga Jual (required)
    - Satuan Unit (required, by name)
    """

    # Validate file type
    if not file.filename.endswith(('.xlsx', '.xls', '.csv')):
        raise HTTPException(status_code=400, detail="File must be Excel (.xlsx, .xls) or CSV (.csv)")

    try:
        # Read file content
        content = await file.read()

        # Parse based on file type
        if file.filename.endswith('.csv'):
            df = pd.read_csv(io.StringIO(content.decode('utf-8')), sep=';')
        else:
            df = pd.read_excel(io.BytesIO(content))

        df.columns = df.columns.str.strip()

        column_mapping = {
            'Item Code': 'code',
            'Nama Item': 'name',
            'SKU': 'sku',
            'Kategori 1': 'kategori_1',
            'Kategori 2': 'kategori_2',
            'Jumlah Unit': 'jumlah_unit',
            'Harga Jual': 'harga_jual',
            'Satuan Unit': 'satuan_unit'
        }

        required_columns = ['Nama Item', 'SKU', 'Satuan Unit']
        missing_columns = [col for col in required_columns if col not in df.columns]
        if missing_columns:
            raise HTTPException(
                status_code=400,
                detail=f"Missing required columns: {', '.join(missing_columns)}"
            )

        df = df.rename(columns=column_mapping)

        categories_lookup = _build_categories_lookup(db)
        satuans_lookup = _build_satuans_lookup(db)
        existing_skus = _get_existing_skus(db)
        existing_codes = _get_existing_codes(db)

        # Process each row
        result = ImportResult(
            total_processed=len(df),
            successful_imports=0,
            failed_imports=0,
            errors=[],
            warnings=[]
        )

        for index, row in df.iterrows():
            try:
                item_data = _process_row(
                    row, index, categories_lookup, satuans_lookup,
                    existing_skus, existing_codes, default_item_type, update_existing  # Add existing_codes parameter
                )

                if item_data is None:
                    continue  # Skip this row

                # Create or update item
                if update_existing and item_data['sku'] in existing_skus:
                    _update_existing_item(db, item_data, existing_skus[item_data['sku']])
                    result.warnings.append({
                        'row': index + 2,
                        'message': f"Updated existing item with SKU: {item_data['sku']}"
                    })
                else:
                    _create_new_item(db, item_data)

                result.successful_imports += 1

            except Exception as e:
                error_msg = str(e)
                result.errors.append({
                    'row': index + 2,
                    'sku': row.get('sku', 'N/A'),
                    'error': error_msg
                })
                result.failed_imports += 1

                if not skip_on_error:
                    db.rollback()
                    raise HTTPException(
                        status_code=400,
                        detail=f"{error_msg}"
                    )

        # Commit all changes
        db.commit()

        return result

    except pd.errors.EmptyDataError:
        raise HTTPException(status_code=400, detail="File is empty or has no data")
    except pd.errors.ParserError as e:
        raise HTTPException(status_code=400, detail=f"Error parsing file: {str(e)}")
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=f"{str(e)}")


def _get_existing_skus(db: Session) -> Dict[str, int]:
    """Get existing SKUs to check for duplicates."""
    items = db.query(Item.sku, Item.id).filter(Item.deleted_at.is_(None)).all()
    return {item.sku: item.id for item in items}


def _get_existing_codes(db: Session) -> Dict[str, int]:
    """Get existing codes to check for duplicates."""
    items = db.query(Item.code, Item.id).filter(
        Item.deleted_at.is_(None),
        Item.code.isnot(None),
        Item.code != ''
    ).all()
    return {item.code: item.id for item in items}


def _process_row(
        row,
        index: int,
        categories_lookup: Dict[str, int],
        satuans_lookup: Dict[str, int],
        existing_skus: Dict[str, int],
        existing_codes: Dict[str, int],  # Add this parameter
        default_item_type: ItemTypeEnum,
        update_existing: bool
) -> Optional[Dict[str, Any]]:

    if pd.isna(row.get('name')) or not str(row.get('name')).strip():
        raise ValueError("Nama Item is required")

    if pd.isna(row.get('sku')) or not str(row.get('sku')).strip():
        raise ValueError("SKU is required")

    # Harga Jual defaults to 0 if empty

    if pd.isna(row.get('satuan_unit')) or not str(row.get('satuan_unit')).strip():
        raise ValueError("Satuan Unit is required")

    sku = str(row['sku']).strip()

    # Check for existing code and skip if it exists
    code = str(row.get('code', '')).strip() if not pd.isna(row.get('code')) else None
    if code and code in existing_codes:
        return None  # Skip this row silently

    if sku in existing_skus and not update_existing:
        raise ValueError(f"SKU '{sku}' already exists. Use update_existing=true to update.")

    satuan_symbol = str(row['satuan_unit']).lower().strip()
    satuan_id = satuans_lookup.get(satuan_symbol)
    if not satuan_id:
        raise ValueError(f"Satuan '{row['satuan_unit']}' tidak ditemukan. tambahkan entri terlebih dahulu.")

    category_one_id = None
    category_two_id = None

    if not pd.isna(row.get('kategori_1')) and str(row.get('kategori_1')).strip():
        cat1_name = str(row['kategori_1']).lower().strip()
        category_one_id = categories_lookup.get(cat1_name)
        if not category_one_id:
            raise ValueError(f"Kategori 1 '{row['kategori_1']}' tidak ditemukan. tambahkan entri terlebih dahulu.")

    if not pd.isna(row.get('kategori_2')) and str(row.get('kategori_2')).strip():
        cat2_name = str(row['kategori_2']).lower().strip()
        category_two_id = categories_lookup.get(cat2_name)
        if not category_two_id:
            raise ValueError(f"Kategori 2 '{row['kategori_2']}' tidak ditemukan. tambahkan entri terlebih dahulu.")

    try:
        if pd.isna(row.get('harga_jual')) or str(row.get('harga_jual')).strip() == '':
            price = Decimal('0')
        else:
            price = Decimal(str(row['harga_jual']).replace(',', '.'))
            if price < 0:
                raise ValueError("Harga Jual must be positive")
    except (ValueError, TypeError):
        raise ValueError(f"Invalid Harga Jual: {row['harga_jual']}")

    # Parse quantity
    total_item = 0
    if not pd.isna(row.get('jumlah_unit')):
        try:
            total_item = int(float(row['jumlah_unit']))
        except (ValueError, TypeError):
            raise ValueError(f"Invalid Jumlah Unit: {row['jumlah_unit']}")

    return {
        'code': code,
        'name': str(row['name']).strip(),
        'sku': sku,
        'type': default_item_type,
        'total_item': total_item,
        'price': price,
        'category_one': category_one_id,
        'category_two': category_two_id,
        'satuan_id': satuan_id,
        'is_active': True
    }


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
        raise HTTPException(status_code=404, detail="Item tidak ditemukan")

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
        raise HTTPException(status_code=404, detail="Item tidak ditemukan")

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
