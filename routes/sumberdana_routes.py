import os
from datetime import datetime, date, time
from typing import List, Optional, Dict

from fastapi import FastAPI,  APIRouter

from fastapi.params import Depends, Query
from sqlalchemy.orm import Session
from starlette import status

from starlette.exceptions import HTTPException

from models.SumberDana import SumberDana
from models.SumberDana import SumberDana
from schemas.PaginatedResponseSchemas import PaginatedResponse
from schemas.SumberDanaSchemas import SumberDanaOut, SumberDanaCreate, SumberDanaUpdate
from database import Base, engine, SessionLocal, get_db
from utils import soft_delete_record

router =APIRouter()


@router.get("", response_model=PaginatedResponse[SumberDanaOut])
async def get_all_sumberdana(
        db: Session = Depends(get_db),
        is_active: Optional[bool] = None,
        search_key: Optional[str] = None,
        contains_deleted : Optional[bool] = False,
        skip: int = Query(0, ge=0),
        limit: int = Query(5, ge=1, le=1000),
        to_date : Optional[date] = Query(None, description="Filter by date"),
        from_date : Optional[date] = Query(None, description="Filter by date")
):

    query = db.query(SumberDana)
    if contains_deleted is False :
        query = query.filter(SumberDana.is_deleted == False)

    if from_date and to_date:
        query = query.filter(
            SumberDana.created_at.between(
                datetime.combine(from_date, time.min),
                datetime.combine(to_date, time.max),
            )
        )
    elif from_date:
        query = query.filter(SumberDana.created_at >= datetime.combine(from_date, time.min))
    elif to_date:
        query = query.filter(SumberDana.created_at <= datetime.combine(to_date, time.max))

    if is_active is not None:
        query = query.filter(SumberDana.is_active == is_active)

    if search_key:
        query = query.filter(SumberDana.name.ilike(f"%{search_key}%"))

    paginated_data =query.offset(skip).limit(limit).all()
    total_data = query.count()
    return {
        "data" : paginated_data,
        "total" : total_data
    }

# Get one
@router.get("/{sumberdana_id}", response_model=SumberDanaOut)
async def get_sumberdana(sumberdana_id: int, db: Session = Depends(get_db)):
    sumberdana = db.query(SumberDana).filter(SumberDana.id == sumberdana_id).first()
    if not sumberdana:
        raise HTTPException(status_code=404, detail="SumberDana not found")
    return sumberdana

# Create
@router.post("", response_model=SumberDanaOut, status_code=status.HTTP_201_CREATED)
async def create_sumberdana(sumberdana_data: SumberDanaCreate, db: Session = Depends(get_db)):

    sumberdana = SumberDana(**sumberdana_data.dict())

    db.add(sumberdana)
    db.commit()
    db.refresh(sumberdana)
    return sumberdana

# Update
@router.put("/{sumberdana_id}", response_model=SumberDanaOut)
async def update_sumberdana(sumberdana_id: int, sumberdana_data: SumberDanaUpdate, db: Session = Depends(get_db)):
    sumberdana = db.query(SumberDana).filter(SumberDana.id == sumberdana_id).first()
    if not sumberdana:
        raise HTTPException(status_code=404, detail="SumberDana not found")

    for field, value in sumberdana_data.dict().items():
        setattr(sumberdana, field, value)

    db.commit()
    db.refresh(sumberdana)
    return sumberdana

# Delete
@router.delete("/{sumberdana_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_sumberdana(sumberdana_id: int, db: Session = Depends(get_db)):
    sumberdana = db.query(SumberDana).filter(SumberDana.id == sumberdana_id).first()
    if not sumberdana:
        raise HTTPException(status_code=404, detail="SumberDana not found")

    soft_delete_record(db,SumberDana, sumberdana_id)
    db.commit()
    return None