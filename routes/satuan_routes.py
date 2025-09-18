import os
from datetime import datetime, date, time
from typing import List, Optional, Dict

from fastapi import FastAPI,  APIRouter

from fastapi.params import Depends, Query
from sqlalchemy.orm import Session
from starlette import status

from starlette.exceptions import HTTPException

from models.Satuan import Satuan
from schemas.PaginatedResponseSchemas import PaginatedResponse
from schemas.SatuanSchemas import SatuanOut, SatuanCreate, SatuanUpdate
from database import Base, engine, SessionLocal, get_db
from utils import soft_delete_record

router =APIRouter()



def _build_satuans_lookup(db: Session) -> Dict[str, int]:
    """Build a lookup dictionary for satuans by name."""
    satuans = db.query(Satuan).filter(Satuan.deleted_at.is_(None)).all()
    return {sat.symbol.lower().strip(): sat.id for sat in satuans}

@router.get("", response_model=PaginatedResponse[SatuanOut])
async def get_all_satuan(
        db: Session = Depends(get_db),
        is_active: Optional[bool] = None,
        search_key: Optional[str] = None,
        contains_deleted : Optional[bool] = False,
        skip: int = Query(0, ge=0),
        limit: int = Query(5, ge=1, le=1000),
        to_date : Optional[date] = Query(None, description="Filter by date"),
        from_date : Optional[date] = Query(None, description="Filter by date")
):
    
    query = db.query(Satuan)
    if contains_deleted is False :
        query = query.filter(Satuan.is_deleted == False)


    if from_date and to_date:
        query = query.filter(
            Satuan.created_at.between(
                datetime.combine(from_date, time.min),
                datetime.combine(to_date, time.max),
            )
        )
    elif from_date:
        query = query.filter(Satuan.created_at >= datetime.combine(from_date, time.min))
    elif to_date:
        query = query.filter(Satuan.created_at <= datetime.combine(to_date, time.max))

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

    soft_delete_record(db,Satuan, satuan_id)
    db.commit()
    return None