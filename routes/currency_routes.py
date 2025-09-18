from datetime import datetime, time, date
from typing import List, Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from starlette import status
from starlette.exceptions import HTTPException

from models.Currency import Currency
from schemas.CurrencySchemas import CurrencyOut, CurrencyCreate, CurrencyUpdate
from database import get_db
from schemas.PaginatedResponseSchemas import PaginatedResponse
from utils import soft_delete_record

router = APIRouter()

# Get all
@router.get("", response_model=PaginatedResponse[CurrencyOut])
async def get_all_currencies(db: Session = Depends(get_db),
                             is_active : Optional[bool] = None,
                             search_key : Optional[str] = None,
                             contains_deleted: Optional[bool] = False,
                             skip: int = Query(0, ge=0),
                             limit: int = Query(5, ge=1, le=1000),
                             to_date : Optional[date] = Query(None, description="Filter by date"),
                             from_date : Optional[date] = Query(None, description="Filter by date")):
    query = db.query(Currency)
    if contains_deleted is False :
        query = query.filter(Currency.is_deleted == False)

    if  is_active is not None:
        query =  query.filter(Currency.is_active == is_active)

    if from_date and to_date:
        query = query.filter(
            Currency.created_at.between(
                datetime.combine(from_date, time.min),
                datetime.combine(to_date, time.max),
            )
        )
    elif from_date:
        query = query.filter(Currency.created_at >= datetime.combine(from_date, time.min))
    elif to_date:
        query = query.filter(Currency.created_at <= datetime.combine(to_date, time.max))

    if search_key:
        query = query.filter(Currency.name.ilike(f"%{search_key}%"))


    totalCount = query.count()
    paginated_data = query.limit(limit).offset(skip).all();

    return {
        "data" : paginated_data ,
        "total" : totalCount
    }


# Get one
@router.get("/{currency_id}", response_model=CurrencyOut)
async def get_currency(currency_id: int, db: Session = Depends(get_db)):
    currency = db.query(Currency).filter(Currency.id == currency_id).first()
    if not currency:
        raise HTTPException(status_code=404, detail="Currency not found")
    return currency

# Create
@router.post("", response_model=CurrencyOut, status_code=status.HTTP_201_CREATED)
async def create_currency(currency_data: CurrencyCreate, db: Session = Depends(get_db)):
    currency = Currency(**currency_data.dict())
    db.add(currency)
    db.commit()
    db.refresh(currency)
    return currency

# Update
@router.put("/{currency_id}", response_model=CurrencyOut)
async def update_currency(currency_id: int, currency_data: CurrencyUpdate, db: Session = Depends(get_db)):
    currency = db.query(Currency).filter(Currency.id == currency_id).first()
    if not currency:
        raise HTTPException(status_code=404, detail="Currency not found")

    for field, value in currency_data.dict().items():
        setattr(currency, field, value)

    db.commit()
    db.refresh(currency)
    return currency

# Delete
@router.delete("/{currency_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_currency(currency_id: int, db: Session = Depends(get_db)):
    currency = db.query(Currency).filter(Currency.id == currency_id).first()
    if not currency:
        raise HTTPException(status_code=404, detail="Currency not found")

    soft_delete_record(db, Currency, currency_id)
    db.commit()
    return None
