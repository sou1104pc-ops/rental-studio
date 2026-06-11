"""SQLite データ層。

無料・サーバ不要で動かすため SQLite を採用。
売上明細（sales）と日報（daily_reports）を保持する。
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime
from typing import Iterable, Iterator

from . import config

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sales (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    source       TEXT    NOT NULL,            -- 'univapay' | 'bank' | 'manual'
    txn_date     TEXT    NOT NULL,            -- ISO 日付 (YYYY-MM-DD)
    amount       INTEGER NOT NULL DEFAULT 0,  -- 売上総額（円）
    fee          INTEGER NOT NULL DEFAULT 0,  -- 手数料（円）
    net          INTEGER NOT NULL DEFAULT 0,  -- 入金額/純額（円）
    customer     TEXT,
    description  TEXT,
    external_id  TEXT,                         -- 取込元の一意キー（重複取込防止）
    raw          TEXT,                         -- 元データ(JSON)
    created_at   TEXT    NOT NULL,
    UNIQUE(source, external_id)
);

CREATE INDEX IF NOT EXISTS idx_sales_txn_date ON sales(txn_date);

CREATE TABLE IF NOT EXISTS daily_reports (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    report_date   TEXT    NOT NULL,
    author        TEXT,
    channel_id    TEXT,
    content       TEXT    NOT NULL,
    ai_generated  INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_reports_date ON daily_reports(report_date);
"""


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with connect() as conn:
        conn.executescript(_SCHEMA)


# ─── 売上 ─────────────────────────────────────────────────────────────────
def insert_sale(
    *,
    source: str,
    txn_date: str,
    amount: int,
    fee: int = 0,
    net: int | None = None,
    customer: str | None = None,
    description: str | None = None,
    external_id: str | None = None,
    raw: dict | None = None,
) -> bool:
    """売上を1件登録。重複（source + external_id）はスキップ。登録できたら True。"""
    if net is None:
        net = amount - fee
    with connect() as conn:
        try:
            conn.execute(
                """INSERT INTO sales
                   (source, txn_date, amount, fee, net, customer, description,
                    external_id, raw, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (
                    source,
                    txn_date,
                    int(amount),
                    int(fee),
                    int(net),
                    customer,
                    description,
                    external_id,
                    json.dumps(raw, ensure_ascii=False) if raw else None,
                    datetime.now().isoformat(timespec="seconds"),
                ),
            )
            return True
        except sqlite3.IntegrityError:
            return False  # 既に取込済み


def bulk_insert_sales(rows: Iterable[dict]) -> tuple[int, int]:
    """複数件登録。(登録件数, スキップ件数) を返す。"""
    inserted = skipped = 0
    for row in rows:
        if insert_sale(**row):
            inserted += 1
        else:
            skipped += 1
    return inserted, skipped


def summarize_sales(start: str, end: str, source: str | None = None) -> dict:
    """期間 [start, end]（両端含む）の売上集計を返す。"""
    q = (
        "SELECT COUNT(*) AS cnt, "
        "COALESCE(SUM(amount),0) AS amount, "
        "COALESCE(SUM(fee),0) AS fee, "
        "COALESCE(SUM(net),0) AS net "
        "FROM sales WHERE txn_date BETWEEN ? AND ?"
    )
    params: list = [start, end]
    if source:
        q += " AND source = ?"
        params.append(source)
    with connect() as conn:
        row = conn.execute(q, params).fetchone()
        by_source = conn.execute(
            "SELECT source, COUNT(*) AS cnt, COALESCE(SUM(amount),0) AS amount, "
            "COALESCE(SUM(net),0) AS net FROM sales "
            "WHERE txn_date BETWEEN ? AND ? GROUP BY source ORDER BY amount DESC",
            [start, end],
        ).fetchall()
    return {
        "start": start,
        "end": end,
        "count": row["cnt"],
        "amount": row["amount"],
        "fee": row["fee"],
        "net": row["net"],
        "by_source": [dict(r) for r in by_source],
    }


def list_sales(start: str, end: str, limit: int = 50) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM sales WHERE txn_date BETWEEN ? AND ? "
            "ORDER BY txn_date DESC, id DESC LIMIT ?",
            [start, end, limit],
        ).fetchall()
    return [dict(r) for r in rows]


# ─── 日報 ─────────────────────────────────────────────────────────────────
def insert_report(
    *,
    report_date: str,
    content: str,
    author: str | None = None,
    channel_id: str | None = None,
    ai_generated: bool = False,
) -> int:
    with connect() as conn:
        cur = conn.execute(
            """INSERT INTO daily_reports
               (report_date, author, channel_id, content, ai_generated, created_at)
               VALUES (?,?,?,?,?,?)""",
            (
                report_date,
                author,
                channel_id,
                content,
                1 if ai_generated else 0,
                datetime.now().isoformat(timespec="seconds"),
            ),
        )
        return int(cur.lastrowid)


def get_reports(report_date: str) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM daily_reports WHERE report_date = ? ORDER BY id",
            [report_date],
        ).fetchall()
    return [dict(r) for r in rows]


def get_notes_for(report_date: str) -> list[str]:
    """その日の手書きメモ（AI生成でない日報）本文を返す。AI日報生成の素材。"""
    return [r["content"] for r in get_reports(report_date) if not r["ai_generated"]]


def today_iso() -> str:
    return date.today().isoformat()
