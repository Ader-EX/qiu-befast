from datetime import datetime, date, time
from typing import List, Optional
from fastapi import APIRouter, Depends, Query
from pydantic.v1.utils import to_lower_camel
from sqlalchemy import Date
from sqlalchemy.orm import Session
from starlette import status
from starlette.exceptions import HTTPException

from models.Warehouse import Warehouse
from schemas.PaginatedResponseSchemas import PaginatedResponse
from schemas.UtilsSchemas import SearchableSelectResponse
from schemas.WarehouseSchemas import WarehouseOut, WarehouseCreate, WarehouseUpdate
from database import get_db
from utils import soft_delete_record

router = APIRouter()

# Get all
@router.get("", response_model=PaginatedResponse[WarehouseOut])
async def get_all_warehouses(
        db: Session = Depends(get_db),
        skip: int = 0,
        limit: int = 10,
        is_active: Optional[bool] = None,
        contains_deleted: Optional[bool] = False, 
        search: Optional[str] = Query(None, description="Search warehouse by name"),
        to_date : Optional[date] = Query(None, description="Filter by date"),
        from_date : Optional[date] = Query(None, description="Filter by date")
):
    query = db.query(Warehouse)
    if contains_deleted is False :
        query = query.filter(Warehouse.is_deleted == False)

    if is_active is not None:
        query = query.filter(Warehouse.is_active == is_active)

    if search:
        query = query.filter(Warehouse.name.ilike(f"%{search}%"))


    if from_date and to_date:
        query = query.filter(
            Warehouse.created_at.between(
                datetime.combine(from_date, time.min),
                datetime.combine(to_date, time.max),
            )
        )
    elif from_date:
        query = query.filter(Warehouse.created_at >= datetime.combine(from_date, time.min))
    elif to_date:
        query = query.filter(Warehouse.created_at <= datetime.combine(to_date, time.max))

    total_count = query.count()
    paginated_data = query.offset(skip).limit(limit).all()

    return {
        "data": paginated_data,
        "total": total_count
    }


@router.get("/{warehouse_id}", response_model=WarehouseOut)
async def get_warehouse(warehouse_id: int, db: Session = Depends(get_db)):
    warehouse = db.query(Warehouse).filter(Warehouse.id == warehouse_id).first()
    if not warehouse:
        raise HTTPException(status_code=404, detail="Warehouse not found")
    return warehouse

@router.get("/searchable/{warehouse_id}", response_model=SearchableSelectResponse)
async def get_warehouse_for_searchable(warehouse_id: int, db: Session = Depends(get_db)):
    warehouse = db.query(Warehouse).filter(Warehouse.id == warehouse_id).first()
    if not warehouse:
        raise HTTPException(status_code=404, detail="Warehouse not found")
    return warehouse


@router.post("", response_model=WarehouseOut, status_code=status.HTTP_201_CREATED)
async def create_warehouse(warehouse_data: WarehouseCreate, db: Session = Depends(get_db)):
    warehouse = Warehouse(**warehouse_data.dict())
    db.add(warehouse)
    db.commit()
    db.refresh(warehouse)
    return warehouse

# Update
@router.put("/{warehouse_id}", response_model=WarehouseOut)
async def update_warehouse(warehouse_id: int, warehouse_data: WarehouseUpdate, db: Session = Depends(get_db)):
    warehouse = db.query(Warehouse).filter(Warehouse.id == warehouse_id).first()
    if not warehouse:
        raise HTTPException(status_code=404, detail="Warehouse not found")

    for field, value in warehouse_data.dict().items():
        setattr(warehouse, field, value)

    db.commit()
    db.refresh(warehouse)
    return warehouse

# Delete
@router.delete("/{warehouse_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_warehouse(warehouse_id: int, db: Session = Depends(get_db)):
    warehouse = db.query(Warehouse).filter(Warehouse.id == warehouse_id).first()
    if not warehouse:
        raise HTTPException(status_code=404, detail="Warehouse not found")

    soft_delete_record(db,Warehouse, warehouse_id)
    db.commit()
    return None
