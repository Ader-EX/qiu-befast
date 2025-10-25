from __future__ import annotations

from datetime import datetime
from decimal import Decimal
import enum

from sqlalchemy import (
    Column, Integer, Numeric, String, DateTime, Date, Boolean,
    Enum as SAEnum, Index, ForeignKey, func
)
from sqlalchemy.orm import relationship

from database import Base
from models.InventoryLedger import SourceTypeEnum


class BatchStock(Base):
    """
    Table untuk tracking FIFO batch stock.
    Setiap pembelian membuat 1 batch baru dengan auto-increment ID.
    
    Contoh:
    - id_batch=1: TV 100 unit @ 10,000 (tanggal: 2025-10-12)
    - id_batch=2: TV 50 unit @ 10,500 (tanggal: 2025-10-15)
    - id_batch=3: Handphone 80 unit @ 5,000 (tanggal: 2025-10-16)
    - id_batch=4: TV 80 unit @ 11,000 (tanggal: 2025-10-18)
    
    Setiap item punya multiple batches dengan id berbeda.
    """
    __tablename__ = "batch_stocks"

    id_batch = Column(Integer, primary_key=True, autoincrement=True) 

    source_id = Column(String(64), nullable=False)
    source_type = Column(SAEnum(SourceTypeEnum), nullable=False, index=True)
    
    item_id = Column(Integer, ForeignKey("items.id"), nullable=False, index=True)
    warehouse_id = Column(Integer, ForeignKey("warehouses.id"), nullable=True, index=True)
    
    tanggal_masuk = Column(Date, nullable=False, index=True)
    
    # Quantity tracking
    qty_masuk = Column(Integer, nullable=False)      # Original quantity dari pembelian
    qty_keluar = Column(Integer, nullable=False, default=0)  # Total yang sudah terpakai
    sisa_qty = Column(Integer, nullable=False)       # qty_masuk - qty_keluar
    
    # Cost tracking
    harga_beli = Column(Numeric(24, 7), nullable=False)  # Harga beli per unit (fixed!)
    nilai_total = Column(Numeric(24, 7), nullable=False)  # qty_masuk * harga_beli
    

    is_open = Column(Boolean, nullable=False, default=True, index=True)
    
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow, server_default=func.now())

    # Relationships
    fifo_logs = relationship("FifoLog", back_populates="batch", cascade="all, delete-orphan")
    item_rel = relationship("Item", back_populates="batch")
    warehouse_rel = relationship("Warehouse", back_populates="batch")

    __table_args__ = (
        Index("ix_batch_item_open_date", "item_id", "is_open", "tanggal_masuk"),
        Index("ix_batch_item_warehouse", "item_id", "warehouse_id"),
    )


class FifoLog(Base):
    """
    Table untuk tracking penggunaan batch pada setiap penjualan.
    Satu penjualan bisa pakai multiple batches.
    
    Contoh INV001 jual 120 unit TV:
    - Row 1: INV001 pakai 100 unit dari id_batch=1 @ 10,000
    - Row 2: INV001 pakai 20 unit dari id_batch=2 @ 10,500
    """
    __tablename__ = "fifo_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    
    # Link ke penjualan
    invoice_id = Column(String(64), nullable=False, index=True)  # INV001, INV002, etc.
    invoice_date = Column(Date, nullable=False, index=True)
    
    # Item yang dijual
    item_id = Column(Integer, nullable=False, index=True)
    
    # Batch yang dipakai (FK to BatchStock.id_batch)
    id_batch = Column(Integer, ForeignKey("batch_stocks.id_batch"), nullable=False, index=True)
    qty_terpakai = Column(Integer, nullable=False)  # Berapa unit diambil dari batch ini
    
    # HPP (Cost of Goods Sold)
    harga_modal = Column(Numeric(24, 7), nullable=False)  # HPP per unit (dari batch.harga_beli)
    total_hpp = Column(Numeric(24, 7), nullable=False)    # qty_terpakai * harga_modal
    
    # Sales info (optional, untuk laporan laba rugi)
    harga_jual = Column(Numeric(24, 7), nullable=True)      # Selling price per unit
    total_penjualan = Column(Numeric(24, 7), nullable=True) # qty_terpakai * harga_jual
    laba_kotor = Column(Numeric(24, 7), nullable=True)      # total_penjualan - total_hpp
    
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, server_default=func.now())

    # Relationships
    batch = relationship("BatchStock", back_populates="fifo_logs")

    __table_args__ = (
        Index("ix_fifo_invoice_item", "invoice_id", "item_id"),
        Index("ix_fifo_batch_date", "id_batch", "invoice_date"),
    )