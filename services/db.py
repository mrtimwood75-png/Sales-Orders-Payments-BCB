from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterable

from config.settings import DB_PATH


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with get_conn() as conn:
        conn.execute(
            '''
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_file TEXT UNIQUE,
                customer_name TEXT,
                customer_email TEXT,
                phone TEXT,
                sales_order TEXT,
                order_date TEXT,
                total_amount REAL,
                prepayment REAL,
                balance_due REAL,
                status TEXT,
                payment_link TEXT,
                envelope_id TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            '''
        )
        conn.execute(
            '''
            CREATE TABLE IF NOT EXISTS sms_jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_file TEXT,
                customer_name TEXT,
                phone TEXT,
                sales_order TEXT,
                total_amount REAL,
                balance_due REAL,
                message TEXT,
                status TEXT,
                sms_message_id TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            '''
        )


def upsert_order(order: dict) -> None:
    cols = [
        'source_file', 'customer_name', 'customer_email', 'phone', 'sales_order', 'order_date',
        'total_amount', 'prepayment', 'balance_due', 'status', 'payment_link', 'envelope_id'
    ]
    values = [order.get(c) for c in cols]
    placeholders = ','.join(['?'] * len(cols))
    updates = ','.join([f'{c}=excluded.{c}' for c in cols[1:]]) + ", updated_at=CURRENT_TIMESTAMP"
    with get_conn() as conn:
        conn.execute(
            f"INSERT INTO orders ({','.join(cols)}) VALUES ({placeholders}) "
            f"ON CONFLICT(source_file) DO UPDATE SET {updates}",
            values,
        )


def list_orders(statuses: Iterable[str] | None = None):
    sql = 'SELECT * FROM orders'
    params = []
    if statuses:
        sql += ' WHERE status IN ({})'.format(','.join(['?'] * len(list(statuses))))
        params = list(statuses)
    sql += ' ORDER BY created_at DESC'
    with get_conn() as conn:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


def update_order(source_file: str, **fields) -> None:
    if not fields:
        return
    assignments = ', '.join([f'{k}=?' for k in fields]) + ', updated_at=CURRENT_TIMESTAMP'
    params = list(fields.values()) + [source_file]
    with get_conn() as conn:
        conn.execute(f'UPDATE orders SET {assignments} WHERE source_file=?', params)


def insert_sms_job(job: dict) -> None:
    cols = ['source_file', 'customer_name', 'phone', 'sales_order', 'total_amount', 'balance_due', 'message', 'status', 'sms_message_id']
    values = [job.get(c) for c in cols]
    placeholders = ','.join(['?'] * len(cols))
    with get_conn() as conn:
        conn.execute(
            f"INSERT INTO sms_jobs ({','.join(cols)}) VALUES ({placeholders})",
            values,
        )


def list_sms_jobs(statuses: Iterable[str] | None = None):
    sql = 'SELECT * FROM sms_jobs'
    params = []
    if statuses:
        sql += ' WHERE status IN ({})'.format(','.join(['?'] * len(list(statuses))))
        params = list(statuses)
    sql += ' ORDER BY created_at DESC'
    with get_conn() as conn:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


def update_sms_job(job_id: int, **fields) -> None:
    if not fields:
        return
    assignments = ', '.join([f'{k}=?' for k in fields]) + ', updated_at=CURRENT_TIMESTAMP'
    params = list(fields.values()) + [job_id]
    with get_conn() as conn:
        conn.execute(f'UPDATE sms_jobs SET {assignments} WHERE id=?', params)
