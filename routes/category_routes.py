from typing import List, Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from starlette import status
from starlette.exceptions import HTTPException

from models.Category import Category
from schemas.CategorySchemas import CategoryOut, CategoryCreate, CategoryUpdate
from database import get_db
from schemas.PaginatedResponseSchemas import PaginatedResponse

router = APIRouter()

# Get all
@router.get("", response_model=PaginatedResponse[CategoryOut])
async def get_all_categories(
        cat_type: int = 0,
        is_active: Optional[bool] = None,
        search_key : Optional[str] = None,
        skip: int = Query(0, ge=0),
        limit: int = Query(5, ge=1, le=1000),
        db: Session = Depends(get_db)
):

    query = db.query(Category)

    if  is_active is not None:
        query =  query.filter(Category.is_active == is_active)

    if search_key:
        query = query.filter(Category.name.ilike(f"%{search_key}%"))

    if cat_type != 0:
        query = query.filter(Category.category_type == cat_type)

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

    db.delete(category)
    db.commit()
    return None
