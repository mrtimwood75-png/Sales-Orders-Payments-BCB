from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Optional


@dataclass
class SalesOrder:
    source_file: str
    customer_name: str = ''
    customer_email: str = ''
    phone: str = ''
    sales_order: str = ''
    order_date: str = ''
    total_amount: Optional[float] = None
    prepayment: Optional[float] = None
    balance_due: Optional[float] = None
    status: str = 'Pending'
    payment_link: str = ''
    envelope_id: str = ''

    def to_dict(self) -> dict:
        return asdict(self)
