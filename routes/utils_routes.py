from datetime import timedelta, datetime
from typing import List, Optional

from fastapi import FastAPI,  APIRouter

from fastapi.params import Depends
from sqlalchemy import extract, func
from sqlalchemy.orm import Session
from starlette import status

from starlette.exceptions import HTTPException

from models.Customer import Customer
from models.Item import Item
from models.Pembelian import Pembelian
from models.Penjualan import Penjualan
from schemas.PaginatedResponseSchemas import PaginatedResponse
from schemas.UserSchemas import UserCreate, TokenSchema, RequestDetails, UserOut, UserUpdate, UserType
from database import  get_db
from schemas.UtilsSchemas import DashboardStatistics
from utils import get_hashed_password, verify_password, create_access_token, create_refresh_token
from models.User import User

router =APIRouter()



@router.get("/statistics", status_code=status.HTTP_200_OK, response_model=DashboardStatistics)
async def get_dashboard_statistics(db: Session = Depends(get_db)):
    now = datetime.now()
    this_month = now.month
    this_year = now.year
    last_month = (now.replace(day=1) - timedelta(days=1)).month
    last_month_year = (now.replace(day=1) - timedelta(days=1)).year

    total_products = db.query(Item).count()
    this_month_products = db.query(Item).filter(
        extract('month', Item.created_at) == this_month,
        extract('year', Item.created_at) == this_year
    ).count()
    last_month_products = db.query(Item).filter(
        extract('month', Item.created_at) == last_month,
        extract('year', Item.created_at) == last_month_year
    ).count()
    percentage_month_products = ((this_month_products - last_month_products) / last_month_products * 100) if last_month_products > 0 else 100.0 if this_month_products > 0 else 0.0

    # Customers
    total_customer = db.query(Customer).count()
    this_month_customer = db.query(Customer).filter(
        extract('month', Customer.created_at) == this_month,
        extract('year', Customer.created_at) == this_year
    ).count()
    last_month_customer = db.query(Customer).filter(
        extract('month', Customer.created_at) == last_month,
        extract('year', Customer.created_at) == last_month_year
    ).count()
    percentage_month_customer = ((this_month_customer - last_month_customer) / last_month_customer * 100) if last_month_customer > 0 else 100.0 if this_month_customer > 0 else 0.0

    # Pembelian
    total_pembelian = db.query(func.coalesce(func.sum(Pembelian.total_price), 0)).scalar()
    this_month_pembelian = db.query(func.coalesce(func.sum(Pembelian.total_price), 0)).filter(
        extract('month', Pembelian.created_at) == this_month,
        extract('year', Pembelian.created_at) == this_year
    ).scalar() or 0
    last_month_pembelian = db.query(func.coalesce(func.sum(Pembelian.total_price), 0)).filter(
        extract('month', Pembelian.created_at) == last_month,
        extract('year', Pembelian.created_at) == last_month_year
    ).scalar() or 0
    percentage_month_pembelian = ((this_month_pembelian - last_month_pembelian) / last_month_pembelian * 100) if last_month_pembelian > 0 else 100.0 if this_month_pembelian > 0 else 0.0

    # Penjualan
    total_penjualan = db.query(func.coalesce(func.sum(Penjualan.total_price), 0)).scalar()
    this_month_penjualan = db.query(func.coalesce(func.sum(Penjualan.total_price), 0)).filter(
        extract('month', Penjualan.created_at) == this_month,
        extract('year', Penjualan.created_at) == this_year
    ).scalar() or 0
    last_month_penjualan = db.query(func.coalesce(func.sum(Penjualan.total_price), 0)).filter(
        extract('month', Penjualan.created_at) == last_month,
        extract('year', Penjualan.created_at) == last_month_year
    ).scalar() or 0
    percentage_month_penjualan = ((this_month_penjualan - last_month_penjualan) / last_month_penjualan * 100) if last_month_penjualan > 0 else 100.0 if this_month_penjualan > 0 else 0.0

    return DashboardStatistics(
        total_products=total_products,
        percentage_month_products=percentage_month_products,
        total_customer=total_customer,
        percentage_month_customer=percentage_month_customer,
        total_pembelian=total_pembelian,
        percentage_month_pembelian=percentage_month_pembelian,
        total_penjualan=total_penjualan,
        percentage_month_penjualan=percentage_month_penjualan
    )