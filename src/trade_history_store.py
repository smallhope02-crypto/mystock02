"""SQLite-backed storage for trade history events."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Optional

try:
    from PyQt5.QtCore import QSettings  # type: ignore
except Exception:  # pragma: no cover - fallback when Qt is unavailable
    QSettings = None  # type: ignore

from .app_paths import ensure_data_dirs, resolve_data_dir, trade_db_path

@dataclass
class TradeEvent:
    created_at: str
    mode: str
    event_type: str
    gubun: Optional[str]
    account: Optional[str]
    code: str
    name: Optional[str]
    side: Optional[str]
    order_no: Optional[str]
    status: Optional[str]
    order_qty: Optional[int]
    order_price: Optional[int]
    exec_no: Optional[str]
    exec_price: Optional[int]
    exec_qty: Optional[int]
    fee: Optional[int]
    tax: Optional[int]
    raw_json: Optional[str]


class TradeHistoryStore:
    """Persist trade events into a local SQLite DB."""

    def __init__(self, db_path: Optional[Path] = None) -> None:
        if db_path is None:
            user_dir = ""
            if QSettings is not None:
                try:
                    secure = QSettings("Mystock02", "AutoTrader")
                    user_dir = secure.value("storage/data_dir", "")
                except Exception:
                    user_dir = ""
            data_dir = resolve_data_dir(user_dir)
            ensure_data_dirs(data_dir)
            db_path = trade_db_path(data_dir)
        self.db_path = db_path
        self._ensure_parent()
        self.init_db()

    def _ensure_parent(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS trade_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT,
                    mode TEXT,
                    event_type TEXT,
                    gubun TEXT,
                    account TEXT,
                    code TEXT,
                    name TEXT,
                    side TEXT,
                    order_no TEXT,
                    status TEXT,
                    order_qty INTEGER,
                    order_price INTEGER,
                    exec_no TEXT,
                    exec_price INTEGER,
                    exec_qty INTEGER,
                    fee INTEGER,
                    tax INTEGER,
                    raw_json TEXT
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_trade_events_created_at ON trade_events(created_at)"
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_trade_events_mode ON trade_events(mode)")

    def insert_event(self, event: dict[str, Any]) -> None:
        created_at = event.get("created_at") or datetime.now().isoformat(sep=" ", timespec="seconds")
        payload = TradeEvent(
            created_at=created_at,
            mode=str(event.get("mode", "")),
            event_type=str(event.get("event_type", "")),
            gubun=event.get("gubun"),
            account=event.get("account"),
            code=str(event.get("code", "")),
            name=event.get("name"),
            side=event.get("side"),
            order_no=event.get("order_no"),
            status=event.get("status"),
            order_qty=event.get("order_qty"),
            order_price=event.get("order_price"),
            exec_no=event.get("exec_no"),
            exec_price=event.get("exec_price"),
            exec_qty=event.get("exec_qty"),
            fee=event.get("fee"),
            tax=event.get("tax"),
            raw_json=event.get("raw_json"),
        )
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO trade_events (
                    created_at, mode, event_type, gubun, account, code, name, side,
                    order_no, status, order_qty, order_price, exec_no, exec_price, exec_qty,
                    fee, tax, raw_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload.created_at,
                    payload.mode,
                    payload.event_type,
                    payload.gubun,
                    payload.account,
                    payload.code,
                    payload.name,
                    payload.side,
                    payload.order_no,
                    payload.status,
                    payload.order_qty,
                    payload.order_price,
                    payload.exec_no,
                    payload.exec_price,
                    payload.exec_qty,
                    payload.fee,
                    payload.tax,
                    payload.raw_json,
                ),
            )

    def query_events(
        self,
        start_date: str,
        end_date: str,
        mode: str = "all",
        code: str | None = None,
        limit: int = 500,
        order_by: str = "created_at DESC",
    ) -> list[dict[str, Any]]:
        order_by = self._sanitize_order_by(order_by)
        filters = ["created_at >= ?", "created_at <= ?"]
        params: list[Any] = [start_date, end_date]
        if mode and mode != "all":
            filters.append("mode = ?")
            params.append(mode)
        if code:
            filters.append("code LIKE ?")
            params.append(f"%{code}%")
        where_clause = " AND ".join(filters)
        sql = f"SELECT * FROM trade_events WHERE {where_clause} ORDER BY {order_by} LIMIT ?"
        params.append(limit)
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    def export_csv(self, rows: Iterable[dict[str, Any]], path: Path) -> None:
        import csv

        rows_list = list(rows)
        if not rows_list:
            path.write_text("", encoding="utf-8")
            return
        fieldnames = list(rows_list[0].keys())
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for row in rows_list:
                writer.writerow(row)

    @staticmethod
    def encode_raw(raw: dict[str, Any]) -> str:
        return json.dumps(raw, ensure_ascii=False)

    @staticmethod
    def _sanitize_order_by(order_by: str) -> str:
        allowed_columns = {
            "created_at",
            "mode",
            "event_type",
            "gubun",
            "account",
            "code",
            "name",
            "side",
            "order_no",
            "status",
            "order_qty",
            "order_price",
            "exec_no",
            "exec_price",
            "exec_qty",
            "fee",
            "tax",
            "raw_json",
            "id",
        }
        if not order_by:
            return "created_at DESC"

        parts = order_by.split()
        if len(parts) == 1:
            column = parts[0]
            direction = "DESC"
        elif len(parts) == 2:
            column, direction = parts
            direction = direction.upper()
            if direction not in {"ASC", "DESC"}:
                return "created_at DESC"
        else:
            return "created_at DESC"

        if column not in allowed_columns:
            return "created_at DESC"

        return f"{column} {direction}"
