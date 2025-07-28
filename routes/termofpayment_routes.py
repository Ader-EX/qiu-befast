import os
from typing import List

from fastapi import FastAPI,  APIRouter

from fastapi.params import Depends
from sqlalchemy.orm import Session
from starlette import status
from schemas.TopSchemas import TopOut, TopCreate, TopUpdate
from starlette.exceptions import HTTPException

from models.TermOfPayment import TermOfPayment
from schemas.SatuanSchemas import SatuanOut, SatuanCreate, SatuanUpdate
from database import Base, engine, SessionLocal, get_db


router =APIRouter()

@router.get("", response_model=List[TopOut])
async def getAllTOP(db : Session = Depends(get_db)):
    return db.query(TermOfPayment).all()

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

    db.delete(top)
    db.commit()
    return None