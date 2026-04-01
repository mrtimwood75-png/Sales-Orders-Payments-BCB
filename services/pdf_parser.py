from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

import fitz

from models.order import SalesOrder


MONEY_PATTERNS = {
    'total_amount': re.compile(r'Total\s+([\d.,]+)', re.IGNORECASE),
    'prepayment': re.compile(r'Prepayment\s+([\d.,]+)', re.IGNORECASE),
    'balance_due': re.compile(r'Balance due\s+([\d.,]+)', re.IGNORECASE),
}


def parse_money(text: str) -> Optional[float]:
    text = text.strip()
    if not text:
        return None
    if text.count(',') == 1 and text.count('.') >= 1:
        text = text.replace('.', '').replace(',', '.')
    elif text.count(',') == 1 and text.count('.') == 0:
        text = text.replace(',', '.')
    else:
        text = text.replace(',', '')
    try:
        return float(text)
    except ValueError:
        return None



def parse_sales_order_pdf(pdf_path: str | Path) -> SalesOrder:
    pdf_path = Path(pdf_path)
    doc = fitz.open(pdf_path)
    first_page_text = doc[0].get_text('text') if doc.page_count else ''
    all_pages = [page.get_text('text') for page in doc]
    full_text = '\n'.join(all_pages)
    reverse_text = '\n'.join(reversed(all_pages))

    customer_name = ''
    lines = [line.strip() for line in first_page_text.splitlines() if line.strip()]
    if lines:
        customer_name = lines[0]

    def find(pattern: str, text: str, flags: int = re.IGNORECASE, group: int = 1) -> str:
        m = re.search(pattern, text, flags)
        return m.group(group).strip() if m else ''

    customer_email = find(r'E-?Mail\s+([^\s]+)', first_page_text)
    phone = find(r'(?:Mobile phone|Phone)\s+([+\d\s]+)', first_page_text)
    sales_order = find(r'Sales order\s+([A-Za-z0-9\-]+)', first_page_text)
    order_date = find(r'Date\s+([\d\-/]+)', first_page_text)

    amounts = {}
    for key, pattern in MONEY_PATTERNS.items():
        m = pattern.search(reverse_text)
        amounts[key] = parse_money(m.group(1)) if m else None

    return SalesOrder(
        source_file=str(pdf_path),
        customer_name=customer_name,
        customer_email=customer_email,
        phone=phone,
        sales_order=sales_order,
        order_date=order_date,
        total_amount=amounts['total_amount'],
        prepayment=amounts['prepayment'],
        balance_due=amounts['balance_due'],
        status='Ready',
    )
