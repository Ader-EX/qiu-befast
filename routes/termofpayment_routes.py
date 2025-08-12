import os
from typing import List, Optional

from fastapi import FastAPI,  APIRouter

from fastapi.params import Depends, Query
from sqlalchemy.orm import Session
from starlette import status

from schemas.PaginatedResponseSchemas import PaginatedResponse
from schemas.TopSchemas import TopOut, TopCreate, TopUpdate
from starlette.exceptions import HTTPException

from models.TermOfPayment import TermOfPayment
from database import Base, engine, SessionLocal, get_db
from utils import soft_delete_record

router =APIRouter()

@router.get("", response_model=PaginatedResponse[TopOut])
async def getAllTOP(db : Session = Depends(get_db),
                    search_key : Optional[str] = None,
                    is_active : Optional[bool] = None,
                    skip: int = Query(0, ge=0),
                    limit: int = Query(5, ge=1, le=1000)):


    query = db.query(TermOfPayment).filter(TermOfPayment.is_deleted == False)

    if  is_active is not None:
        query =  query.filter(TermOfPayment.is_active == is_active)

    if search_key:
        query = query.filter(TermOfPayment.name.ilike(f"%{search_key}%"))


    total_data = query.count()
    paginated_data = query.offset(skip).limit(limit).all()

    return {
    "data" : paginated_data,
    "total" : total_data
    }

@router.get("/{top_id}", response_model=TopOut, status_code=status.HTTP_200_OK)
async def getTOPById(top_id : int, db : Session = Depends(get_db)):
    result = db.query(TermOfPayment).filter(top_id == TermOfPayment.id).first()
    if not result:
        raise HTTPException(status_code=404, detail="Term of Payment not found")
    return result


@router.post("", response_model=TopOut, status_code=status.HTTP_201_CREATED)
async def createTOP(top_data :TopCreate ,db: Session = Depends(get_db)):
    top  = TermOfPayment(**top_data.dict())
    db.add(top)
    db.commit()
    db.refresh(top)
    return top


@router.put("/{top_id}", response_model=TopUpdate, status_code=status.HTTP_200_OK)
async def updateTOP(top_data :  TopUpdate,top_id : int, db:Session = Depends(get_db)):
    top = db.query(TermOfPayment).filter(top_id  == TermOfPayment.id).first()
    if not top:
        raise HTTPException(status_code=404, detail="Term of Payment ID tidak ditemukan")

    for field, value in top_data.dict().items():
        setattr(top, field, value)

    db.commit()
    db.refresh(top)
    return top


@router.delete("/{top_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_top(top_id: int, db: Session = Depends(get_db)):
    top = db.query(TermOfPayment).filter(TermOfPayment.id == top_id).first()
    if not top:
        raise HTTPException(status_code=404, detail="TOP not found")

    soft_delete_record(db, TermOfPayment, top_id)
    db.commit()
    return None