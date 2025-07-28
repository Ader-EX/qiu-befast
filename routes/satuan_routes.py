import os
from typing import List

from fastapi import FastAPI,  APIRouter

from fastapi.params import Depends
from sqlalchemy.orm import Session
from starlette import status

from starlette.exceptions import HTTPException

from models.Satuan import Satuan
from schemas.SatuanSchemas import SatuanOut, SatuanCreate, SatuanUpdate
from database import Base, engine, SessionLocal, get_db




# id = Column(Integer, primary_key=True, index=True)
# name = Column(String(100), nullable=False)
# symbol = Column(String(10), nullable=False)
# is_active = Column(Boolean, default=True, nullable=False)


router =APIRouter()


@router.get("", response_model=List[SatuanOut])
async def get_all_satuan(db: Session = Depends(get_db)):
    return db.query(Satuan).all()

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