from decimal import Decimal
from datetime import date
from typing import List, Optional, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import and_, desc

from models.BatchStock import BatchStock, FifoLog, SourceTypeEnum

class FifoService:
    """Service untuk handle FIFO logic"""
    
    @staticmethod
    def rollback_latest_sale(
        db: Session,
        invoice_id: str,
        invoice_date: date,
    ):
        """Rollback the most recent sale"""
        # 1. Check if this is the latest sale
        latest_sale = db.query(FifoLog).order_by(
            desc(FifoLog.invoice_date), 
            desc(FifoLog.id)
        ).first()
        
        if not latest_sale or latest_sale.invoice_id != invoice_id:
            raise ValueError("Can only rollback the most recent sale!")
        
        # 2. Get all FifoLog entries for this invoice
        logs = db.query(FifoLog).filter(FifoLog.invoice_id == invoice_id).all()
        
        # 3. Restore each batch
        for log in logs:
            batch = db.query(BatchStock).get(log.id_batch)
            if batch:
                batch.qty_keluar -= log.qty_terpakai
                batch.sisa_qty += log.qty_terpakai
                batch.is_open = True  # Reopen if was closed
        
        # 4. Delete the FifoLog entries
        db.query(FifoLog).filter(FifoLog.invoice_id == invoice_id).delete()
        
        db.commit()
    
    @staticmethod
    def create_batch_from_purchase(
        db: Session,
        source_id: str,
        source_type: SourceTypeEnum,
        item_id: int,
        warehouse_id: Optional[int],
        tanggal_masuk: date,
        qty_masuk: int,
        harga_beli: Decimal
    ) -> BatchStock:
        """
        Buat batch baru dari transaksi pembelian.
        id_batch akan auto-increment.
        
        Args:
            source_id: ID dari source document (PO number, transfer number, etc)
            source_type: Type dari source (PURCHASE_ORDER, STOCK_TRANSFER, etc)
            item_id: ID dari item
            warehouse_id: ID warehouse (optional)
            tanggal_masuk: Tanggal batch masuk
            qty_masuk: Quantity masuk
            harga_beli: Harga beli per unit
        
        Example:
            create_batch_from_purchase(
                db, 
                source_id="PO-001",
                source_type=SourceTypeEnum.PURCHASE_ORDER,
                item_id=123, 
                warehouse_id=1,
                tanggal_masuk=date(2025,10,12), 
                qty_masuk=100, 
                harga_beli=Decimal("10000")
            )
        """
        nilai_total = Decimal(qty_masuk) * harga_beli
        
        batch = BatchStock(
            source_id=source_id,
            source_type=source_type,
            item_id=item_id,
            warehouse_id=warehouse_id,
            tanggal_masuk=tanggal_masuk,
            qty_masuk=qty_masuk,
            qty_keluar=0,
            sisa_qty=qty_masuk,
            harga_beli=harga_beli,
            nilai_total=nilai_total,
            is_open=True
        )
        
        db.add(batch)
        db.commit()
        db.refresh(batch)
        
        return batch
    
    @staticmethod
    def get_open_batches(
        db: Session,
        item_id: int,
        warehouse_id: Optional[int] = None
    ) -> List[BatchStock]:
        """
        Ambil semua batch yang masih OPEN, sorted by tanggal_masuk ASC (FIFO).
        """
        query = db.query(BatchStock).filter(
            and_(
                BatchStock.item_id == item_id,
                BatchStock.is_open == True,
                BatchStock.sisa_qty > 0
            )
        )
        
        if warehouse_id is not None:
            query = query.filter(BatchStock.warehouse_id == warehouse_id)
        
        # FIFO: oldest first
        query = query.order_by(BatchStock.tanggal_masuk.asc(), BatchStock.id_batch.asc())
        
        return query.all()
    
    @staticmethod
    def process_sale_fifo(
        db: Session,
        invoice_id: str,
        invoice_date: date,
        item_id: int,
        qty_terjual: int,
        harga_jual_per_unit: Decimal,
        warehouse_id: Optional[int] = None
    ) -> Tuple[Decimal, List[FifoLog]]:
        """
        Process penjualan menggunakan FIFO.
        
        Args:
            invoice_id: ID invoice (e.g., "INV001")
            invoice_date: Tanggal invoice
            item_id: ID item yang dijual
            qty_terjual: Quantity yang dijual
            harga_jual_per_unit: Harga jual per unit
            warehouse_id: ID warehouse (optional)
        
        Returns:
            (total_hpp, list_of_fifo_logs)
        
        Example:
            total_hpp, logs = process_sale_fifo(
                db, "INV001", date(2025,10,12), item_id=123, qty_terjual=120, 
                harga_jual_per_unit=Decimal("13000")
            )
        """
        sisa_qty_keluar = qty_terjual
        total_hpp = Decimal("0")
        fifo_logs = []
        
        # Get open batches (FIFO order)
        batches = FifoService.get_open_batches(db, item_id, warehouse_id)
        
        if not batches:
            raise ValueError(f"No open batches available for item_id={item_id}")
        
        for batch in batches:
            if batch.sisa_qty == 0:
                continue
            
            # Berapa unit yang dipakai dari batch ini?
            qty_dipakai = min(batch.sisa_qty, sisa_qty_keluar)
            
            # Update batch
            batch.qty_keluar += qty_dipakai
            batch.sisa_qty -= qty_dipakai
            
            # Close batch if empty
            if batch.sisa_qty == 0:
                batch.is_open = False
            
            # Calculate HPP
            hpp_batch = qty_dipakai * batch.harga_beli
            total_hpp += hpp_batch
            
            # Calculate profit
            penjualan_batch = qty_dipakai * harga_jual_per_unit
            laba_batch = penjualan_batch - hpp_batch
            
            # Create FIFO log
            fifo_log = FifoLog(
                invoice_id=invoice_id,
                invoice_date=invoice_date,
                item_id=item_id,
                id_batch=batch.id_batch,
                qty_terpakai=qty_dipakai,
                harga_modal=batch.harga_beli,
                total_hpp=hpp_batch,
                harga_jual=harga_jual_per_unit,
                total_penjualan=penjualan_batch,
                laba_kotor=laba_batch
            )
            
            db.add(fifo_log)
            fifo_logs.append(fifo_log)
            
            # Update remaining
            sisa_qty_keluar -= qty_dipakai
            
            # Done?
            if sisa_qty_keluar == 0:
                break
        
        # Check if we fulfilled the entire order
        if sisa_qty_keluar > 0:
            raise ValueError(
                f"Insufficient stock! Still need {sisa_qty_keluar} units for item_id={item_id}"
            )
        
        db.commit()
        
        return total_hpp, fifo_logs
    
    @staticmethod
    def get_laporan_laba_rugi(
        db: Session,
        start_date: date,
        end_date: date,
        item_id: Optional[int] = None
    ) -> List[dict]:
        """
        Generate Laporan Laba Rugi dari FIFO logs.
        
        Returns list of dicts dengan format:
        {
            'tanggal': date,
            'no_invoice': str,
            'item_id': int,
            'qty_terjual': int,
            'hpp': Decimal,
            'total_hpp': Decimal,
            'harga_jual': Decimal,
            'total_penjualan': Decimal,
            'laba_kotor': Decimal
        }
        """
        query = db.query(FifoLog).filter(
            and_(
                FifoLog.invoice_date >= start_date,
                FifoLog.invoice_date <= end_date
            )
        )
        
        if item_id is not None:
            query = query.filter(FifoLog.item_id == item_id)
        
        query = query.order_by(FifoLog.invoice_date.asc(), FifoLog.invoice_id.asc())
        
        logs = query.all()
        
        # Group by invoice
        invoice_groups = {}
        for log in logs:
            key = (log.invoice_date, log.invoice_id, log.item_id)
            if key not in invoice_groups:
                invoice_groups[key] = {
                    'tanggal': log.invoice_date,
                    'no_invoice': log.invoice_id,
                    'item_id': log.item_id,
                    'qty_terjual': 0,
                    'total_hpp': Decimal("0"),
                    'total_penjualan': Decimal("0"),
                    'laba_kotor': Decimal("0"),
                    'harga_jual': log.harga_jual  # Assume same for all
                }
            
            invoice_groups[key]['qty_terjual'] += log.qty_terpakai
            invoice_groups[key]['total_hpp'] += log.total_hpp
            invoice_groups[key]['total_penjualan'] += log.total_penjualan
            invoice_groups[key]['laba_kotor'] += log.laba_kotor
        
        # Convert to list and add HPP per unit
        result = []
        for data in invoice_groups.values():
            data['hpp'] = data['total_hpp'] / data['qty_terjual'] if data['qty_terjual'] > 0 else Decimal("0")
            result.append(data)
        
        return result
    
    @staticmethod
    def get_stock_card(
        db: Session,
        item_id: int,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None
    ) -> List[dict]:
        """
        Generate Stock Card report.
        
        Returns list of dicts dengan format:
        {
            'tanggal': date,
            'batch': str,
            'source_id': str,
            'source_type': str,
            'item_id': int,
            'qty_masuk': int,
            'harga_beli': Decimal,
            'qty_keluar': int,
            'sisa_qty': int,
            'hpp_sisa': Decimal
        }
        """
        query = db.query(BatchStock).filter(BatchStock.item_id == item_id)
        
        if start_date:
            query = query.filter(BatchStock.tanggal_masuk >= start_date)
        if end_date:
            query = query.filter(BatchStock.tanggal_masuk <= end_date)
        
        query = query.order_by(BatchStock.tanggal_masuk.asc())
        
        batches = query.all()
        
        result = []
        for batch in batches:
            result.append({
                'tanggal': batch.tanggal_masuk,
                'batch': batch.id_batch,
                'source_id': batch.source_id,
                'source_type': batch.source_type.value if batch.source_type else None,
                'item_id': batch.item_id,
                'qty_masuk': batch.qty_masuk,
                'harga_beli': batch.harga_beli,
                'qty_keluar': batch.qty_keluar,
                'sisa_qty': batch.sisa_qty,
                'hpp_sisa': batch.sisa_qty * batch.harga_beli
            })
        
        return result
    
    @staticmethod
    def get_batch_details(
        db: Session,
        id_batch: int
    ) -> Optional[dict]:
        """
        Get detailed information about a specific batch.
        
        Returns dict dengan format:
        {
            'id_batch': int,
            'source_id': str,
            'source_type': str,
            'item_id': int,
            'warehouse_id': int,
            'tanggal_masuk': date,
            'qty_masuk': int,
            'qty_keluar': int,
            'sisa_qty': int,
            'harga_beli': Decimal,
            'nilai_total': Decimal,
            'is_open': bool,
            'fifo_logs': List[dict]
        }
        """
        batch = db.query(BatchStock).filter(BatchStock.id_batch == id_batch).first()
        
        if not batch:
            return None
        
        # Get FIFO logs for this batch
        logs = db.query(FifoLog).filter(FifoLog.id_batch == id_batch).all()
        
        fifo_logs = []
        for log in logs:
            fifo_logs.append({
                'invoice_id': log.invoice_id,
                'invoice_date': log.invoice_date,
                'qty_terpakai': log.qty_terpakai,
                'total_hpp': log.total_hpp,
                'harga_jual': log.harga_jual,
                'total_penjualan': log.total_penjualan,
                'laba_kotor': log.laba_kotor
            })
        
        return {
            'id_batch': batch.id_batch,
            'source_id': batch.source_id,
            'source_type': batch.source_type.value if batch.source_type else None,
            'item_id': batch.item_id,
            'warehouse_id': batch.warehouse_id,
            'tanggal_masuk': batch.tanggal_masuk,
            'qty_masuk': batch.qty_masuk,
            'qty_keluar': batch.qty_keluar,
            'sisa_qty': batch.sisa_qty,
            'harga_beli': batch.harga_beli,
            'nilai_total': batch.nilai_total,
            'is_open': batch.is_open,
            'fifo_logs': fifo_logs
        }
    
    @staticmethod
    def get_batches_by_source(
        db: Session,
        source_id: str,
        source_type: Optional[SourceTypeEnum] = None
    ) -> List[dict]:
        """
        Get all batches from a specific source document.
        
        Useful untuk tracking semua batches yang dibuat dari:
        - Purchase Order tertentu
        - Stock Transfer tertentu
        - etc.
        
        Returns list of batch details
        """
        query = db.query(BatchStock).filter(BatchStock.source_id == source_id)
        
        if source_type:
            query = query.filter(BatchStock.source_type == source_type)
        
        batches = query.order_by(BatchStock.tanggal_masuk.asc()).all()
        
        result = []
        for batch in batches:
            result.append({
                'id_batch': batch.id_batch,
                'source_id': batch.source_id,
                'source_type': batch.source_type.value if batch.source_type else None,
                'item_id': batch.item_id,
                'warehouse_id': batch.warehouse_id,
                'tanggal_masuk': batch.tanggal_masuk,
                'qty_masuk': batch.qty_masuk,
                'qty_keluar': batch.qty_keluar,
                'sisa_qty': batch.sisa_qty,
                'harga_beli': batch.harga_beli,
                'nilai_total': batch.nilai_total,
                'is_open': batch.is_open
            })
        
        return result