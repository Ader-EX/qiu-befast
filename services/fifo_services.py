from decimal import Decimal
from datetime import date
from typing import List, Optional, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import and_, desc

from models.BatchStock import BatchStock, FifoLog, SourceTypeEnum

class FifoService:
    """Service untuk handle FIFO logic"""
   
    @staticmethod
    def rollback_sale(
        db: Session,
        invoice_id: str,
        rollback_date: Optional[date] = None
    ) -> dict:
        """
        Rollback sale by creating REVERSAL entries (not deleting).
        Simple qty-based validation - if batch has enough qty_keluar, rollback is allowed.
        
        Args:
            invoice_id: Invoice to rollback
            rollback_date: Date of rollback (default: today)
        
        Returns:
            {
                'success': bool,
                'invoice_id': str,
                'reversal_id': str,
                'items_rolled_back': int,
                'message': str
            }
        """
        if rollback_date is None:
            rollback_date = date.today()
        
        # 1. Get original sale logs
        original_logs = db.query(FifoLog).filter(
            FifoLog.invoice_id == invoice_id
        ).all()
        
        if not original_logs:
            raise ValueError(f"Sale {invoice_id} not found")
        
        # 2. PRE-CHECK: Verify each batch has enough qty_keluar to rollback
        insufficient_batches = []
        blocking_invoices = set()
        
        for log in original_logs:
            batch = db.query(BatchStock).filter(
                BatchStock.id_batch == log.id_batch
            ).first()
            
            if not batch:
                raise ValueError(f"Batch {log.id_batch} not found")
            
            # Simple check: Would rolling back make qty_keluar negative?
            new_qty_keluar = batch.qty_keluar - log.qty_terpakai
            
            if new_qty_keluar < 0:
                # This batch doesn't have enough qty_keluar to support this rollback
                insufficient_batches.append({
                    'batch_id': batch.id_batch,
                    'current_qty_keluar': batch.qty_keluar,
                    'trying_to_rollback': log.qty_terpakai,
                    'deficit': abs(new_qty_keluar)
                })
                
                # Find which invoice consumed from this batch AFTER the one we're trying to rollback
                last_usage = db.query(FifoLog).filter(
                    and_(
                        FifoLog.id_batch == log.id_batch,
                        ~FifoLog.invoice_id.like("%-ROLLBACK")
                    )
                ).order_by(FifoLog.created_at.desc()).first()
                
                if last_usage and last_usage.invoice_id != invoice_id:
                    blocking_invoices.add(last_usage.invoice_id)
        
        # If any batch check failed, report error
        if insufficient_batches:
            error_msg = f"Cannot rollback {invoice_id}. "
            
            if blocking_invoices:
                error_msg += f"Newer transactions have consumed from the same batches: {', '.join(sorted(blocking_invoices))}. "
                error_msg += "You must rollback those transactions first (LIFO order)."
            else:
                # This shouldn't happen in normal operations
                error_details = "; ".join([
                    f"Batch {b['batch_id']}: has qty_keluar={b['current_qty_keluar']}, "
                    f"need {b['trying_to_rollback']} (deficit: {b['deficit']})"
                    for b in insufficient_batches
                ])
                error_msg += f"Insufficient qty_keluar in batches: {error_details}"
            
            raise ValueError(error_msg)
        
        # 3. All checks passed - create reversal entries
        reversal_id = f"{invoice_id}-ROLLBACK"
        reversal_logs = []
        
        for log in original_logs:
            batch = db.query(BatchStock).filter(
                BatchStock.id_batch == log.id_batch
            ).first()
            
            # Restore batch quantities
            batch.qty_keluar -= log.qty_terpakai
            batch.sisa_qty += log.qty_terpakai
            
            # Reopen batch if it has available quantity
            if batch.sisa_qty > 0:
                batch.is_open = True
            
            # Create REVERSAL log entry
            reversal_log = FifoLog(
                invoice_id=reversal_id,
                invoice_date=rollback_date,
                item_id=log.item_id,
                id_batch=log.id_batch,
                qty_terpakai=log.qty_terpakai,  # Keep positive for audit
                harga_modal=log.harga_modal,
                total_hpp=-log.total_hpp,  # Negative (reversal)
                harga_jual=log.harga_jual,
                total_penjualan=-log.total_penjualan,  # Negative (reversal)
                laba_kotor=-log.laba_kotor  # Negative (reversal)
            )
            
            db.add(reversal_log)
            reversal_logs.append(reversal_log)
        
        db.commit()
        
        return {
            'success': True,
            'invoice_id': invoice_id,
            'reversal_id': reversal_id,
            'items_rolled_back': len(reversal_logs),
            'message': f"Successfully rolled back {invoice_id}. Created {len(reversal_logs)} reversal entries."
        }


    @staticmethod
    def get_laporan_laba_rugi(
        db: Session,
        start_date: date,
        end_date: date,
        item_id: Optional[int] = None,
        include_rollbacks: bool = False
    ) -> List[dict]:
        """
        Generate Laporan Laba Rugi dari FIFO logs.
        Completely excludes rolled-back transactions from report.
        
        Args:
            start_date: Start date for report
            end_date: End date for report
            item_id: Optional filter by item
            include_rollbacks: If False (default), excludes rolled-back sales
        """
        query = db.query(FifoLog).filter(
            and_(
                FifoLog.invoice_date >= start_date,
                FifoLog.invoice_date <= end_date
            )
        )
        
        if item_id is not None:
            query = query.filter(FifoLog.item_id == item_id)
        
        # Always exclude the rollback entries themselves
        query = query.filter(~FifoLog.invoice_id.like("%-ROLLBACK"))
        
        query = query.order_by(FifoLog.invoice_date.asc(), FifoLog.invoice_id.asc())
        
        logs = query.all()
        
        # Find all rolled-back invoice IDs
        rolled_back_invoices = set()
        if not include_rollbacks:
            rollback_logs = db.query(FifoLog.invoice_id).filter(
                FifoLog.invoice_id.like("%-ROLLBACK")
            ).distinct().all()
            
            for row in rollback_logs:
                original_id = row.invoice_id.replace('-ROLLBACK', '')
                rolled_back_invoices.add(original_id)
        
        # Group by invoice
        invoice_groups = {}
        for log in logs:
            # Skip if this invoice has been rolled back
            if log.invoice_id in rolled_back_invoices:
                continue
            
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
                    'harga_jual': log.harga_jual,
                    'is_rollback': False
                }
            
            # Sum up quantities and amounts
            invoice_groups[key]['qty_terjual'] += log.qty_terpakai
            invoice_groups[key]['total_hpp'] += log.total_hpp
            invoice_groups[key]['total_penjualan'] += log.total_penjualan
            invoice_groups[key]['laba_kotor'] += log.laba_kotor
        
        # Convert to list and calculate averages
        result = []
        for data in invoice_groups.values():
            if data['qty_terjual'] > 0:
                data['hpp'] = data['total_hpp'] / data['qty_terjual']
            else:
                data['hpp'] = Decimal("0")
            result.append(data)
        
        return result


    @staticmethod
    def get_rollback_chain(
        db: Session,
        item_id: int,
        warehouse_id: Optional[int] = None
    ) -> List[dict]:
        """
        Get the proper rollback order for all active sales of an item.
        Returns list ordered by required rollback sequence (newest first).
        
        Useful for showing users: "You must rollback these invoices in this order"
        """
        # Get all batches for this item
        query = db.query(BatchStock).filter(
            BatchStock.item_id == item_id
        )
        
        if warehouse_id:
            query = query.filter(BatchStock.warehouse_id == warehouse_id)
        
        batches = query.all()
        batch_ids = [b.id_batch for b in batches]
        
        if not batch_ids:
            return []
        
        # Get all FIFO logs for these batches (excluding rollbacks)
        logs = db.query(FifoLog).filter(
            and_(
                FifoLog.id_batch.in_(batch_ids),
                ~FifoLog.invoice_id.like("%-ROLLBACK")
            )
        ).order_by(FifoLog.created_at.desc()).all()  # Newest first
        
        # Get unique invoices in LIFO order
        seen = set()
        result = []
        
        for log in logs:
            if log.invoice_id not in seen:
                seen.add(log.invoice_id)
                
                # Check if already rolled back
                has_rollback = db.query(FifoLog).filter(
                    FifoLog.invoice_id == f"{log.invoice_id}-ROLLBACK"
                ).first() is not None
                
                if not has_rollback:
                    result.append({
                        'invoice_id': log.invoice_id,
                        'invoice_date': log.invoice_date,
                        'item_id': log.item_id,
                        'order': len(result) + 1,
                        'must_rollback_first': result[0]['invoice_id'] if result else None
                    })
        
        return result
    
    @staticmethod
    def get_net_fifo_logs(
        db: Session,
        invoice_id: str
    ) -> List[dict]:
        """
        Get net effect of sale + rollback entries.
        Useful for reports to show actual impact.
        
        Returns list of net effects per batch.
        """
        # Get original sale
        sale_logs = db.query(FifoLog).filter(
            FifoLog.invoice_id == invoice_id
        ).all()
        
        # Get rollback (if exists)
        rollback_logs = db.query(FifoLog).filter(
            FifoLog.invoice_id == f"{invoice_id}-ROLLBACK"
        ).all()
        
        # Group by batch
        batch_summary = {}
        
        for log in sale_logs:
            if log.id_batch not in batch_summary:
                batch_summary[log.id_batch] = {
                    'batch_id': log.id_batch,
                    'item_id': log.item_id,
                    'qty_sold': 0,
                    'qty_rolled_back': 0,
                    'net_qty': 0,
                    'total_hpp': Decimal('0'),
                    'total_sales': Decimal('0'),
                    'net_profit': Decimal('0')
                }
            
            batch_summary[log.id_batch]['qty_sold'] += log.qty_terpakai
            batch_summary[log.id_batch]['total_hpp'] += log.total_hpp
            batch_summary[log.id_batch]['total_sales'] += log.total_penjualan
            batch_summary[log.id_batch]['net_profit'] += log.laba_kotor
        
        for log in rollback_logs:
            if log.id_batch in batch_summary:
                batch_summary[log.id_batch]['qty_rolled_back'] += log.qty_terpakai
                batch_summary[log.id_batch]['total_hpp'] += log.total_hpp  # Already negative
                batch_summary[log.id_batch]['total_sales'] += log.total_penjualan  # Already negative
                batch_summary[log.id_batch]['net_profit'] += log.laba_kotor  # Already negative
        
        # Calculate net qty
        for batch_id in batch_summary:
            summary = batch_summary[batch_id]
            summary['net_qty'] = summary['qty_sold'] - summary['qty_rolled_back']
        
        return list(batch_summary.values())
    
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
        Creates NEGATIVE qty entries for sales.
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
            
            # Create FIFO log (SALE = negative impact on stock)
            fifo_log = FifoLog(
                invoice_id=invoice_id,
                invoice_date=invoice_date,
                item_id=item_id,
                id_batch=batch.id_batch,
                qty_terpakai=qty_dipakai,  # Positive number
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
        item_id: Optional[int] = None,
        include_rollbacks: bool = False
    ) -> List[dict]:
        """
        Generate Laporan Laba Rugi dari FIFO logs.
        
        Args:
            include_rollbacks: If False, excludes rollback entries from report
        """
        query = db.query(FifoLog).filter(
            and_(
                FifoLog.invoice_date >= start_date,
                FifoLog.invoice_date <= end_date
            )
        )
        
        if item_id is not None:
            query = query.filter(FifoLog.item_id == item_id)
        
        if not include_rollbacks:
            # Exclude rollback entries
            query = query.filter(~FifoLog.invoice_id.like("%-ROLLBACK"))
        
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
                    'harga_jual': log.harga_jual,
                    'is_rollback': '-ROLLBACK' in log.invoice_id
                }
            
            invoice_groups[key]['qty_terjual'] += log.qty_terpakai
            invoice_groups[key]['total_hpp'] += log.total_hpp
            invoice_groups[key]['total_penjualan'] += log.total_penjualan
            invoice_groups[key]['laba_kotor'] += log.laba_kotor
        
        # Convert to list and add HPP per unit
        result = []
        for data in invoice_groups.values():
            if data['qty_terjual'] > 0:
                data['hpp'] = data['total_hpp'] / data['qty_terjual']
            else:
                data['hpp'] = Decimal("0")
            result.append(data)
        
        return result
    
    @staticmethod
    def get_stock_card(
        db: Session,
        item_id: int,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None
    ) -> List[dict]:
        """Generate Stock Card report."""
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
        """Get detailed information about a specific batch including rollbacks."""
        batch = db.query(BatchStock).filter(BatchStock.id_batch == id_batch).first()
        
        if not batch:
            return None
        
        # Get FIFO logs for this batch (including rollbacks)
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
                'laba_kotor': log.laba_kotor,
                'is_rollback': '-ROLLBACK' in log.invoice_id
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
        """Get all batches from a specific source document."""
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