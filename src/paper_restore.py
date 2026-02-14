from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional


@dataclass
class RestoredPosition:
    symbol: str
    qty: int
    avg_price: float


@dataclass
class PaperRestoreResult:
    ok: bool
    base_cash: float
    cash: float
    positions: Dict[str, RestoredPosition]
    buy_count_today: Dict[str, int]
    warnings: List[str]
    scanned_events: int
    used_reset: bool


def _parse_cash_from_raw(raw_json: str) -> Optional[float]:
    try:
        obj = json.loads(raw_json or "{}")
        cash_val = obj.get("cash", None)
        return float(cash_val) if cash_val is not None else None
    except Exception:
        return None


def restore_paper_state_from_db(
    db_path: Path,
    start_ts: str,
    end_ts: str,
    fallback_initial_cash: float,
) -> PaperRestoreResult:
    """
    start_ts/end_ts: 'YYYY-MM-DD HH:MM:SS' (로컬/KST 기준으로 사용)
    """
    warnings: List[str] = []
    if not db_path.exists():
        return PaperRestoreResult(
            ok=False,
            base_cash=fallback_initial_cash,
            cash=fallback_initial_cash,
            positions={},
            buy_count_today={},
            warnings=[f"db not found: {db_path}"],
            scanned_events=0,
            used_reset=False,
        )

    cash = float(fallback_initial_cash)
    base_cash = float(fallback_initial_cash)
    positions_qty: Dict[str, int] = {}
    positions_avg: Dict[str, float] = {}
    buy_count_today: Dict[str, int] = {}
    used_reset = False
    scanned = 0

    try:
        con = sqlite3.connect(str(db_path))
        con.row_factory = sqlite3.Row
        cur = con.cursor()
        cur.execute(
            """
            SELECT id, created_at, event_type, code, side, exec_price, exec_qty, order_price, order_qty, raw_json
            FROM trade_events
            WHERE mode='paper'
              AND event_type IN ('paper_fill','paper_reset')
              AND created_at >= ?
              AND created_at <= ?
            ORDER BY created_at ASC, id ASC
            """,
            (start_ts, end_ts),
        )
        rows = cur.fetchall()
        scanned = len(rows)

        for row in rows:
            event_type = (row["event_type"] or "").strip()
            if event_type == "paper_reset":
                reset_cash = _parse_cash_from_raw(row["raw_json"] or "")
                if reset_cash is None:
                    try:
                        reset_cash = float(row["order_price"])
                    except Exception:
                        reset_cash = None
                if reset_cash is None:
                    warnings.append("paper_reset found but cash not parseable; ignored")
                    continue
                used_reset = True
                base_cash = float(reset_cash)
                cash = float(reset_cash)
                positions_qty.clear()
                positions_avg.clear()
                buy_count_today.clear()
                continue

            side = (row["side"] or "").strip().lower()
            symbol = (row["code"] or "").strip()
            if not symbol:
                warnings.append("paper_fill with empty code ignored")
                continue

            qty = row["exec_qty"] if row["exec_qty"] is not None else row["order_qty"]
            px = row["exec_price"] if row["exec_price"] is not None else row["order_price"]
            try:
                qty = int(qty)
                px = float(px)
            except Exception:
                warnings.append(f"invalid fill row ignored: {symbol} qty={qty} px={px}")
                continue
            if qty <= 0 or px <= 0:
                continue

            if side == "buy":
                cash -= qty * px
                prev_qty = positions_qty.get(symbol, 0)
                prev_avg = positions_avg.get(symbol, 0.0)
                new_qty = prev_qty + qty
                new_avg = ((prev_avg * prev_qty) + (px * qty)) / new_qty if new_qty > 0 else px
                positions_qty[symbol] = new_qty
                positions_avg[symbol] = new_avg
                buy_count_today[symbol] = buy_count_today.get(symbol, 0) + 1
            elif side == "sell":
                cash += qty * px
                prev_qty = positions_qty.get(symbol, 0)
                if prev_qty <= 0:
                    warnings.append(f"sell without position: {symbol} qty={qty}")
                    continue
                new_qty = prev_qty - qty
                if new_qty <= 0:
                    positions_qty.pop(symbol, None)
                    positions_avg.pop(symbol, None)
                else:
                    positions_qty[symbol] = new_qty
            else:
                warnings.append(f"unknown side ignored: {side}")

        con.close()
    except Exception as exc:
        return PaperRestoreResult(
            ok=False,
            base_cash=base_cash,
            cash=cash,
            positions={},
            buy_count_today={},
            warnings=[f"restore failed: {exc}"],
            scanned_events=scanned,
            used_reset=used_reset,
        )

    restored: Dict[str, RestoredPosition] = {}
    for sym, qty in positions_qty.items():
        if qty > 0:
            restored[sym] = RestoredPosition(sym, qty, float(positions_avg.get(sym, 0.0)))

    return PaperRestoreResult(
        ok=True,
        base_cash=base_cash,
        cash=cash,
        positions=restored,
        buy_count_today=buy_count_today,
        warnings=warnings,
        scanned_events=scanned,
        used_reset=used_reset,
    )
