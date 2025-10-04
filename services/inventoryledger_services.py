from __future__ import annotations

from datetime import datetime, date, timezone
from decimal import Decimal
from typing import List, Optional, Dict
import pytz
from sqlalchemy import select, and_, desc, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from models.InventoryLedger import InventoryLedger
from models.InventoryLedger import SourceTypeEnum


class InventoryService:
    """Service layer for inventory ledger operations"""

    def __init__(self, db: Session):
        self.db = db
        
    def _now(self) -> datetime:
    # Set the timezone to Jakarta Time (Asia/Jakarta, which is UTC+7)
        jakarta_tz = pytz.timezone('Asia/Jakarta')
        # Get the current time in the specified timezone
        return datetime.now(jakarta_tz)


    def _get_last_ledger_entry(
            self,
            item_id: int,
            before_date: Optional[date] = None
    ) -> Optional[InventoryLedger]:
        """Get the most recent ledger entry for an item"""
        query = select(InventoryLedger).where(
            and_(
                InventoryLedger.item_id == item_id,
                InventoryLedger.voided == False
            )
        )

        if before_date:
            query = query.where(InventoryLedger.trx_date <= before_date)

        query = query.order_by(
            desc(InventoryLedger.trx_date),
            desc(InventoryLedger.id)
        ).limit(1)

        result = self.db.execute(query)
        return result.scalar_one_or_none()

    def _generate_order_key(
            self,
            item_id: int,
            trx_date: date
    ) -> str:
        """Generate unique order key for strict ordering"""
        # Get max sequence for this item and date
        query = select(func.count()).where(
            and_(
                InventoryLedger.item_id == item_id,
                InventoryLedger.trx_date == trx_date
            )
        )
        result = self.db.execute(query)
        sequence = result.scalar() or 0

        return f"{trx_date.isoformat()}_{sequence + 1:010d}"
    def post_inventory_in(
        self,
        item_id: int,
        source_type: SourceTypeEnum,
        source_id: str,
        qty: int,
        unit_price: Decimal,
        trx_date: Optional[datetime] = None,   # <-- keep param for signature
        reason_code: Optional[str] = None
    ) -> InventoryLedger:
        # FORCE: always use "now", ignore any caller-provided date
        trx_dt = self._now()

        if qty <= 0:
            raise ValueError("Quantity must be positive for IN movements")
        if unit_price < 0:
            raise ValueError("Unit price cannot be negative")

        last_entry = self._get_last_ledger_entry(item_id)  # latest row
        prev_qty = last_entry.cumulative_qty if last_entry else 0
        prev_value = last_entry.cumulative_value if last_entry else Decimal("0")

        value_in = Decimal(qty) * unit_price
        new_cumulative_qty = prev_qty + qty
        new_cumulative_value = prev_value + value_in
        moving_avg_cost = (new_cumulative_value / Decimal(new_cumulative_qty)) if new_cumulative_qty > 0 else Decimal("0")

        order_key = self._generate_order_key(item_id, trx_dt)

        ledger_entry = InventoryLedger(
            item_id=item_id,
            source_type=source_type,
            source_id=source_id,
            qty_in=qty,
            qty_out=0,
            unit_price=unit_price,
            value_in=value_in,
            cumulative_qty=new_cumulative_qty,
            moving_avg_cost=moving_avg_cost,
            cumulative_value=new_cumulative_value,
            trx_date=trx_dt,     # <-- always now
            order_key=order_key,
            reason_code=reason_code,
            voided=False
        )
        self.db.add(ledger_entry)
        self.db.commit()
        self.db.refresh(ledger_entry)
        return ledger_entry

    def post_inventory_out(
        self,
        item_id: int,
        source_type: SourceTypeEnum,
        source_id: str,
        qty: int,
        trx_date: Optional[datetime] = None,   # <-- keep param
        reason_code: Optional[str] = None
    ) -> InventoryLedger:
        # FORCE: always use "now"
        trx_dt = self._now()

        if qty <= 0:
            raise ValueError("Quantity must be positive for OUT movements")

        last_entry = self._get_last_ledger_entry(item_id)
        if not last_entry:
            raise ValueError(f"No inventory found for item {item_id}")

        prev_qty = last_entry.cumulative_qty
        prev_value = last_entry.cumulative_value
        current_moving_avg = last_entry.moving_avg_cost

        if prev_qty < qty:
            raise ValueError(f"Insufficient stock. Available: {prev_qty}, Requested: {qty}")

        new_cumulative_qty = prev_qty - qty
        value_out = Decimal(qty) * current_moving_avg
        new_cumulative_value = prev_value - value_out
        if new_cumulative_value < 0:
            new_cumulative_value = Decimal("0")

        order_key = self._generate_order_key(item_id, trx_dt)

        ledger_entry = InventoryLedger(
            item_id=item_id,
            source_type=source_type,
            source_id=source_id,
            qty_in=0,
            qty_out=qty,
            unit_price=current_moving_avg,
            value_in=Decimal("0"),
            cumulative_qty=new_cumulative_qty,
            moving_avg_cost=current_moving_avg,
            cumulative_value=new_cumulative_value,
            trx_date=trx_dt,     
            order_key=order_key,
            reason_code=reason_code,
            voided=False
        )
        self.db.add(ledger_entry)
        self.db.commit()
        self.db.refresh(ledger_entry)
        return ledger_entry

    def get_current_stock(self, item_id: int) -> Dict:
        """
        Get current stock balance and moving average cost for an item

        Returns:
            Dict with qty, moving_avg_cost, and total_value
        """
        last_entry = self._get_last_ledger_entry(item_id)

        if not last_entry:
            return {
                "item_id": item_id,
                "qty": 0,
                "moving_avg_cost": Decimal("0"),
                "total_value": Decimal("0")
            }

        return {
            "item_id": item_id,
            "qty": last_entry.cumulative_qty,
            "moving_avg_cost": last_entry.moving_avg_cost,
            "total_value": last_entry.cumulative_value
        }
    def _recompute_from(self, item_id: int, start_date: date) -> None:
        """
        Recompute cumulative_qty, cumulative_value, moving_avg_cost for all rows
        with trx_date >= start_date, ordered strictly by (trx_date, id).
        """
        q = select(InventoryLedger).where(
            and_(
                InventoryLedger.item_id == item_id,
                InventoryLedger.voided == False,
                InventoryLedger.trx_date >= start_date,
            )
        ).order_by(InventoryLedger.trx_date.asc(), InventoryLedger.id.asc())

        rows = list(self.db.execute(q).scalars().all())

        # Seed from the last entry strictly BEFORE start_date
        prev = self._get_last_ledger_entry(item_id, before_date=start_date.fromordinal(start_date.toordinal()-1))
        cum_qty = prev.cumulative_qty if prev else 0
        cum_val = prev.cumulative_value if prev else Decimal("0")
        mac = prev.moving_avg_cost if prev else Decimal("0")

        for r in rows:
            if r.qty_in > 0:
                value_in = Decimal(r.qty_in) * Decimal(str(r.unit_price))
                cum_qty = cum_qty + r.qty_in
                cum_val = cum_val + value_in
                mac = (cum_val / Decimal(cum_qty)) if cum_qty > 0 else Decimal("0")
                r.value_in = value_in
            elif r.qty_out > 0:
                value_out = Decimal(r.qty_out) * mac
                cum_qty = cum_qty - r.qty_out
                cum_val = cum_val - value_out
                if cum_val < 0:  # rounding safety
                    cum_val = Decimal("0")
                # mac stays the same on OUT

            r.cumulative_qty = cum_qty
            r.cumulative_value = cum_val
            r.moving_avg_cost = mac

        self.db.commit()


    def void_ledger_entry(
            self,
            ledger_id: int,
            reason: str
    ) -> InventoryLedger:
        """
        Void a ledger entry and create a reversal entry

        Args:
            ledger_id: ID of the ledger entry to void
            reason: Reason for voiding

        Returns:
            The reversal ledger entry
        """
        # Get the original entry
        query = select(InventoryLedger).where(InventoryLedger.id == ledger_id)
        result = self.db.execute(query)
        original_entry = result.scalar_one_or_none()

        if not original_entry:
            raise ValueError(f"Ledger entry {ledger_id} not found")

        if original_entry.voided:
            raise ValueError(f"Ledger entry {ledger_id} is already voided")

        # Mark original as voided
        original_entry.voided = True

        # Create reversal entry (opposite movement)
        if original_entry.qty_in > 0:
            # Original was IN, so reverse with OUT
            reversal = self.post_inventory_out(
                item_id=original_entry.item_id,
                source_type=original_entry.source_type,
                source_id=f"REVERSAL_{original_entry.source_id}",
                qty=original_entry.qty_in,
                trx_date=date.today(),
                reason_code=f"REVERSAL: {reason}"
            )
        else:
            # Original was OUT, so reverse with IN
            reversal = self.post_inventory_in(
                item_id=original_entry.item_id,
                source_type=original_entry.source_type,
                source_id=f"REVERSAL_{original_entry.source_id}",
                qty=original_entry.qty_out,
                unit_price=original_entry.unit_price,
                trx_date=date.today(),
                reason_code=f"REVERSAL: {reason}"
            )

        # Link the reversal
        reversal.reversal_of_ledger_id = ledger_id

        self.db.commit()
        return reversal

    def void_ledger_entry_by_source(self, source_id: str, reason: str):
        """Find the latest non-voided ledger row by source_id and void it (creates reversal)."""
        q = select(InventoryLedger.id).where(
            and_(InventoryLedger.source_id == source_id, InventoryLedger.voided == False)
        ).order_by(desc(InventoryLedger.trx_date), desc(InventoryLedger.id)).limit(1)

        ledger_id = self.db.execute(q).scalar_one_or_none()
        if ledger_id is None:
            return None  # Nothing to void (first-time post)
        return self.void_ledger_entry(ledger_id, reason)



    def get_inventory_report(
            self,
            date_from: date,
            date_to: date,
            item_ids: Optional[List[int]] = None
    ) -> List[Dict]:
        """
        Get inventory report for display in UI table

        Returns list of items with:
        - item_id
        - item_name (you'll need to join with items table)
        - qty_masuk (sum of qty_in)
        - qty_keluar (sum of qty_out)
        - qty_balance (final cumulative_qty)
        - harga_masuk (weighted average of incoming prices)
        - harga_keluar (moving average cost)
        - hpp (cost of goods sold)
        """
        query = select(
            InventoryLedger.item_id,
            func.sum(InventoryLedger.qty_in).label('qty_masuk'),
            func.sum(InventoryLedger.qty_out).label('qty_keluar'),
            func.sum(
                func.case(
                    (InventoryLedger.qty_in > 0, InventoryLedger.value_in),
                    else_=Decimal("0")
                )
            ).label('total_value_in'),
            func.sum(
                func.case(
                    (InventoryLedger.qty_out > 0,
                     InventoryLedger.qty_out * InventoryLedger.unit_price),
                    else_=Decimal("0")
                )
            ).label('hpp')
        ).where(
            and_(
                InventoryLedger.trx_date >= date_from,
                InventoryLedger.trx_date <= date_to,
                InventoryLedger.voided == False
            )
        )

        if item_ids:
            query = query.where(InventoryLedger.item_id.in_(item_ids))

        query = query.group_by(InventoryLedger.item_id)

        result =  self.db.execute(query)
        rows = result.all()

        report = []
        for row in rows:
            # Get current balance
            current_stock =  self.get_current_stock(row.item_id)

            # Calculate weighted average incoming price
            harga_masuk = Decimal("0")
            if row.qty_masuk > 0:
                harga_masuk = row.total_value_in / Decimal(row.qty_masuk)

            report.append({
                "item_id": row.item_id,
                # "item_name": "",  # Join with items table to get name
                "qty_masuk": row.qty_masuk or 0,
                "qty_keluar": row.qty_keluar or 0,
                "qty_balance": current_stock["qty"],
                "harga_masuk": harga_masuk,
                "harga_keluar": current_stock["moving_avg_cost"],
                "hpp": row.hpp or Decimal("0")
            })

        return report

#
# Usage examples:
def example_usage(db: AsyncSession):
    """Example of how to use the InventoryService"""

    service = InventoryService(db)

    # 1. Import initial stock (from item import)
    service.post_inventory_in(
        item_id=1,
        source_type=SourceTypeEnum.ITEM,
        source_id="IMPORT_ITEM:1",
        qty=100,
        unit_price=Decimal("10.50"),
        trx_date=date(2025, 1, 1),
        reason_code="Initial import"
    )

    # 2. Post a purchase (Pembelian)
    service.post_inventory_in(
        item_id=1,
        source_type=SourceTypeEnum.PEMBELIAN,
        source_id="PEMBELIAN_ITEM:12345",
        qty=50,
        unit_price=Decimal("11.00"),
        trx_date=date(2025, 1, 15),
        reason_code="Purchase from supplier"
    )

    # 3. Post a sale (Penjualan)
    service.post_inventory_out(
        item_id=1,
        source_type=SourceTypeEnum.PENJUALAN,
        source_id="PENJUALAN_ITEM:67890",
        qty=30,
        trx_date=date(2025, 1, 20),
        reason_code="Sale to customer"
    )

    # 4. Stock adjustment IN
    service.post_inventory_in(
        item_id=1,
        source_type=SourceTypeEnum.IN,
        source_id="ADJUSTMENT_IN:001",
        qty=10,
        unit_price=Decimal("10.50"),
        trx_date=date(2025, 1, 25),
        reason_code="Found missing stock"
    )

    # 5. Stock adjustment OUT
    service.post_inventory_out(
        item_id=1,
        source_type=SourceTypeEnum.OUT,
        source_id="ADJUSTMENT_OUT:001",
        qty=5,
        trx_date=date(2025, 1, 26),
        reason_code="Damaged goods"
    )

    # 6. Get current stock
    stock = service.get_current_stock(item_id=1)
    print(f"Current stock: {stock}")

    # 7. Get inventory report
    report = service.get_inventory_report(
        date_from=date(2025, 1, 1),
        date_to=date(2025, 1, 31)
    )
    print(f"Report: {report}")