
import pytz
from sqlalchemy import Enum

from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, Text
from database import Base
import enum



def get_jkt_now():
    """
    Returns a timezone-aware datetime object set to Asia/Jakarta (WIB, UTC+7).
    This function must be called as the default for the Column.
    """
    # Define the Jakarta timezone object
    jakarta_tz = pytz.timezone('Asia/Jakarta')
    # Get the current time localized to Jakarta
    return datetime.now(jakarta_tz)

class AuditActionEnum(enum.Enum):
    # Generic actions
    CREATE = "CREATE"
    UPDATE = "UPDATE"
    DELETE = "DELETE"

    # Status changes
    STATUS_CHANGE = "STATUS_CHANGE"

    # Specific actions
    ITEM_ADD = "ITEM_ADD"
    ITEM_UPDATE = "ITEM_UPDATE"
    ITEM_REMOVE = "ITEM_REMOVE"
    PAYMENT_CREATE = "PAYMENT_CREATE"
    PAYMENT_UPDATE = "PAYMENT_UPDATE"
    RETURN_CREATE = "RETURN_CREATE"
    RETURN_UPDATE = "RETURN_UPDATE"


class AuditEntityEnum(enum.Enum):
    PEMBELIAN = "PEMBELIAN"
    PENJUALAN = "PENJUALAN"
    PEMBELIAN_ITEM = "PEMBELIAN_ITEM"
    PENJUALAN_ITEM = "PENJUALAN_ITEM"
    PEMBAYARAN = "PEMBAYARAN"
    PENGEMBALIAN = "PENGEMBALIAN"
    CUSTOMER = "CUSTOMER"
    VENDOR = "VENDOR"
    ITEM = "ITEM"
    STOCK_ADJUSTMENT = "STOCK_ADJUSTMENT"


class AuditTrail(Base):
    __tablename__ = "audit_trails"

    id = Column(Integer, primary_key=True, index=True)
    entity_id = Column(String(100), nullable=False)  # ID of the thing being tracked
    entity_type = Column(Enum(AuditEntityEnum), nullable=False)  # Type of entity
    description = Column(Text, nullable=False)  # What happened (human-readable)
    user_name = Column(String(100), nullable=False)  # Who did it
    timestamp = Column(DateTime(timezone=True), default=get_jkt_now, nullable=False)

    class Config:
        orm_mode = True