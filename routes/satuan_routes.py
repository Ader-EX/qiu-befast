import os
from typing import List, Optional

from fastapi import FastAPI,  APIRouter

from fastapi.params import Depends, Query
from sqlalchemy.orm import Session
from starlette import status

from starlette.exceptions import HTTPException

from models.Satuan import Satuan
from schemas.PaginatedResponseSchemas import PaginatedResponse
from schemas.SatuanSchemas import SatuanOut, SatuanCreate, SatuanUpdate
from database import Base, engine, SessionLocal, get_db





router =APIRouter()


@router.get("", response_model=PaginatedResponse[SatuanOut])
async def get_all_satuan(
        db: Session = Depends(get_db),
        is_active: Optional[bool] = None,
        search_key: Optional[str] = None,
        skip: int = Query(0, ge=0),
        limit: int = Query(5, ge=1, le=1000)
):
    query = db.query(Satuan)

    if is_active is not None:
        query = query.filter(Satuan.is_active == is_active)

    if search_key:
        query = query.filter(Satuan.name.ilike(f"%{search_key}%"))

    paginated_data =query.offset(skip).limit(limit).all()
    total_data = query.count()
    return {
        "data" : paginated_data,
        "total" : total_data
    }

# Get one
@router.get("/{satuan_id}", response_model=SatuanOut)
async def get_satuan(satuan_id: int, db: Session = Depends(get_db)):
    satuan = db.query(Satuan).filter(Satuan.id == satuan_id).first()
    if not satuan:
        raise HTTPException(status_code=404, detail="Satuan not found")
    return satuan

# Create
@router.post("", response_model=SatuanOut, status_code=status.HTTP_201_CREATED)
async def create_satuan(satuan_data: SatuanCreate, db: Session = Depends(get_db)):
    satuan = Satuan(**satuan_data.dict())
    db.add(satuan)
    db.commit()
    db.refresh(satuan)
    return satuan

# Update
@router.put("/{satuan_id}", response_model=SatuanOut)
async def update_satuan(satuan_id: int, satuan_data: SatuanUpdate, db: Session = Depends(get_db)):
    satuan = db.query(Satuan).filter(Satuan.id == satuan_id).first()
    if not satuan:
        raise HTTPException(status_code=404, detail="Satuan not found")

    for field, value in satuan_data.dict().items():
        setattr(satuan, field, value)

    db.commit()
    db.refresh(satuan)
    return satuan

# Delete
@router.delete("/{satuan_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_satuan(satuan_id: int, db: Session = Depends(get_db)):
    satuan = db.query(Satuan).filter(Satuan.id == satuan_id).first()
    if not satuan:
        raise HTTPException(status_code=404, detail="Satuan not found")

    db.delete(satuan)
    db.commit()
    return None