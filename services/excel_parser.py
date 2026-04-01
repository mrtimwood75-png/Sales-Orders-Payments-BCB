from __future__ import annotations

from pathlib import Path
from typing import List

import pandas as pd


def normalise_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [str(c).strip().lower().replace(' ', '_') for c in df.columns]
    return df


def parse_ready_delivery_report(path: str | Path) -> pd.DataFrame:
    df = pd.read_excel(path)
    df = normalise_columns(df)
    rename_map = {
        'customer': 'customer_name',
        'name': 'customer_name',
        'mobile': 'phone',
        'phone_number': 'phone',
        'order_no': 'sales_order',
        'order_number': 'sales_order',
        'balance': 'balance_due',
        'amount_payable': 'balance_due',
        'total': 'total_amount',
    }
    df = df.rename(columns={k: v for k, v in rename_map.items() if k in df.columns})
    for required in ['customer_name', 'phone', 'sales_order']:
        if required not in df.columns:
            raise ValueError(f'Missing required column: {required}')
    if 'balance_due' not in df.columns:
        df['balance_due'] = None
    if 'total_amount' not in df.columns:
        df['total_amount'] = None
    return df
