from typing import List, Optional
from fastapi import APIRouter, Depends, Query
from pydantic.v1.utils import to_lower_camel
from sqlalchemy.orm import Session
from starlette import status
from starlette.exceptions import HTTPException

from models.Warehouse import Warehouse
from schemas.PaginatedResponseSchemas import PaginatedResponse
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
        search: Optional[str] = Query(None, description="Search warehouse by name"),
):
    query = db.query(Warehouse).filter(Warehouse.is_deleted == False)

    if is_active is not None:
        query = query.filter(Warehouse.is_active == is_active)

    if search:
        query = query.filter(Warehouse.name.ilike(f"%{search}%"))

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
