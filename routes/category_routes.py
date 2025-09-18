from datetime import datetime, date, time
from typing import List, Optional, Dict
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from starlette import status
from starlette.exceptions import HTTPException

from models.Category import Category
from schemas.CategorySchemas import CategoryOut, CategoryCreate, CategoryUpdate
from database import get_db
from schemas.PaginatedResponseSchemas import PaginatedResponse
from utils import soft_delete_record

router = APIRouter()


def _build_categories_lookup(db: Session) -> Dict[str, int]:
    """Build a lookup dictionary for categories by name."""
    categories = db.query(Category).filter(Category.deleted_at.is_(None)).all()
    return {cat.name.lower().strip(): cat.id for cat in categories}
# Get all
@router.get("", response_model=PaginatedResponse[CategoryOut])
async def get_all_categories(
        cat_type: int = 0,
        is_active: Optional[bool] = None,
        search_key : Optional[str] = None,
        contains_deleted: Optional[bool] = False, 
        skip: int = Query(0, ge=0),
        limit: int = Query(5, ge=1, le=1000),
        db: Session = Depends(get_db),
        to_date : Optional[date] = Query(None, description="Filter by date"),
        from_date : Optional[date] = Query(None, description="Filter by date")
):

    query = db.query(Category)
    
    if contains_deleted is False:
        query = query.filter(Category.is_deleted == False)

    if  is_active is not None:
        query =  query.filter(Category.is_active == is_active)

    if search_key:
        query = query.filter(Category.name.ilike(f"%{search_key}%"))

    if cat_type != 0:
        query = query.filter(Category.category_type == cat_type)

    if from_date and to_date:
        query = query.filter(
            Category.created_at.between(
                datetime.combine(from_date, time.min),
                datetime.combine(to_date, time.max),
            )
        )
    elif from_date:
        query = query.filter(Category.created_at >= datetime.combine(from_date, time.min))
    elif to_date:
        query = query.filter(Category.created_at <= datetime.combine(to_date, time.max))

    paginated_data =query.offset(skip).limit(limit).all()
    total_count = query.count()

    return {
        "data": paginated_data,
        "total": total_count
    }



@router.get("/{category_id}", response_model=CategoryOut)
async def get_category(category_id: int, db: Session = Depends(get_db)):
    category = db.query(Category).filter(Category.id == category_id).first()
    if not category:
        raise HTTPException(status_code=404, detail="Category not found")
    return category

# Create
@router.post("", response_model=CategoryOut, status_code=status.HTTP_201_CREATED)
async def create_category(category_data: CategoryCreate, db: Session = Depends(get_db)):
    category = Category(**category_data.dict())
    db.add(category)
    db.commit()
    db.refresh(category)
    return category

# Update
@router.put("/{category_id}", response_model=CategoryOut)
async def update_category(category_id: int, category_data: CategoryUpdate, db: Session = Depends(get_db)):
    category = db.query(Category).filter(Category.id == category_id).first()
    if not category:
        raise HTTPException(status_code=404, detail="Category not found")

    for field, value in category_data.dict().items():
        setattr(category, field, value)

    db.commit()
    db.refresh(category)
    return category

# Delete
@router.delete("/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_category(category_id: int, db: Session = Depends(get_db)):
    category = db.query(Category).filter(Category.id == category_id).first()
    if not category:
        raise HTTPException(status_code=404, detail="Category not found")

    soft_delete_record(db,Category, category_id)
    db.commit()

    return None
