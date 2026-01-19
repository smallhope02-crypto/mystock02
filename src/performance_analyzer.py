"""Performance analysis utilities based on trade history fills."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, Iterable, List, Optional

from .trade_history_store import TradeHistoryStore

logger = logging.getLogger(__name__)


@dataclass
class Fill:
    ts: datetime
    mode: str
    code: str
    name: Optional[str]
    side: str
    price: int
    qty: int
    fee: int = 0
    tax: int = 0
    order_no: Optional[str] = None
    exec_no: Optional[str] = None


@dataclass
class ClosedLot:
    code: str
    name: Optional[str]
    entry_ts: datetime
    exit_ts: datetime
    entry_price: int
    exit_price: int
    qty: int
    gross_pnl: int
    fee: int
    tax: int
    net_pnl: int
    hold_seconds: int


@dataclass
class SymbolPerf:
    code: str
    name: Optional[str]
    closed_trades: int
    wins: int
    losses: int
    win_rate: float
    buy_amount: int
    sell_amount: int
    gross_profit_sum: int
    gross_loss_sum: int
    net_pnl_sum: int
    return_pct: float
    avg_win: float
    avg_loss: float
    avg_pnl: float
    profit_factor: float
    avg_hold_minutes: float
    fee_sum: int
    tax_sum: int


@dataclass
class DailyPerf:
    date: str
    total_closed_trades: int
    wins: int
    losses: int
    win_rate: float
    net_pnl_sum: int
    gross_pnl_sum: int
    fee_sum: int
    tax_sum: int
    avg_pnl: float
    best_trade: Optional[ClosedLot]
    worst_trade: Optional[ClosedLot]
    best_symbol: Optional[str]
    worst_symbol: Optional[str]
    time_bucket_perf: List[dict]


def _parse_datetime(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value)
    except Exception:
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")


def load_fills(
    store: TradeHistoryStore,
    start_dt: datetime,
    end_dt: datetime,
    mode_filter: str = "all",
) -> List[Fill]:
    start = start_dt.strftime("%Y-%m-%d %H:%M:%S")
    end = end_dt.strftime("%Y-%m-%d %H:%M:%S")
    rows = store.query_events(start, end, mode=mode_filter, limit=10000, order_by="created_at ASC")
    fills: List[Fill] = []
    skipped: Dict[str, int] = {
        "missing_price": 0,
        "missing_qty": 0,
        "invalid_side": 0,
        "not_fill": 0,
    }
    for row in rows:
        event_type = row.get("event_type")
        created_at = row.get("created_at")
        if not created_at:
            skipped["not_fill"] += 1
            continue
        ts = _parse_datetime(created_at)
        if event_type == "paper_fill":
            side = str(row.get("side", "")).strip()
            if side not in ("buy", "sell"):
                skipped["invalid_side"] += 1
                continue
            price = int(row.get("exec_price") or 0)
            qty = int(row.get("exec_qty") or 0)
            if price <= 0:
                skipped["missing_price"] += 1
                continue
            if qty <= 0:
                skipped["missing_qty"] += 1
                continue
            fills.append(
                Fill(
                    ts=ts,
                    mode=str(row.get("mode", "")),
                    code=str(row.get("code", "")),
                    name=row.get("name"),
                    side=side,
                    price=price,
                    qty=qty,
                    fee=0,
                    tax=0,
                    order_no=row.get("order_no"),
                    exec_no=row.get("exec_no"),
                )
            )
            continue

        if event_type == "chejan":
            gubun = str(row.get("gubun", "")).strip()
            status = str(row.get("status", "")).strip()
            if gubun != "0" or status != "체결":
                skipped["not_fill"] += 1
                continue
            side_raw = str(row.get("side", "")).strip()
            if side_raw == "2":
                side = "buy"
            elif side_raw == "1":
                side = "sell"
            else:
                skipped["invalid_side"] += 1
                continue
            price = int(row.get("exec_price") or 0)
            qty = int(row.get("exec_qty") or 0)
            if price <= 0:
                skipped["missing_price"] += 1
                continue
            if qty <= 0:
                skipped["missing_qty"] += 1
                continue
            fills.append(
                Fill(
                    ts=ts,
                    mode=str(row.get("mode", "")),
                    code=str(row.get("code", "")),
                    name=row.get("name"),
                    side=side,
                    price=price,
                    qty=qty,
                    fee=int(row.get("fee") or 0),
                    tax=int(row.get("tax") or 0),
                    order_no=row.get("order_no"),
                    exec_no=row.get("exec_no"),
                )
            )
            continue

        skipped["not_fill"] += 1

    logger.info(
        "[REPORT_PARSE] events=%d fills=%d skipped=%s",
        len(rows),
        len(fills),
        skipped,
    )
    return fills


def build_closed_lots(fills: Iterable[Fill], include_open: bool = False) -> List[ClosedLot]:
    by_code: Dict[str, List[Fill]] = {}
    for fill in fills:
        by_code.setdefault(fill.code, []).append(fill)
    closed: List[ClosedLot] = []
    for code, items in by_code.items():
        items.sort(key=lambda f: f.ts)
        fifo: List[Fill] = []
        for fill in items:
            if fill.side == "buy":
                fifo.append(fill)
                continue
            if not fifo:
                logger.warning("[REPORT] sell before buy: code=%s ts=%s", code, fill.ts.isoformat())
                continue
            sell_qty_left = fill.qty
            fee_left = fill.fee
            tax_left = fill.tax
            while sell_qty_left > 0 and fifo:
                buy_fill = fifo[0]
                match_qty = min(buy_fill.qty, sell_qty_left)
                if match_qty <= 0:
                    fifo.pop(0)
                    continue
                ratio = match_qty / sell_qty_left if sell_qty_left else 0
                fee_alloc = int(round(fee_left * ratio))
                tax_alloc = int(round(tax_left * ratio))
                fee_left -= fee_alloc
                tax_left -= tax_alloc
                gross = (fill.price - buy_fill.price) * match_qty
                net = gross - fee_alloc - tax_alloc
                hold_seconds = int((fill.ts - buy_fill.ts).total_seconds())
                closed.append(
                    ClosedLot(
                        code=code,
                        name=buy_fill.name or fill.name,
                        entry_ts=buy_fill.ts,
                        exit_ts=fill.ts,
                        entry_price=buy_fill.price,
                        exit_price=fill.price,
                        qty=match_qty,
                        gross_pnl=gross,
                        fee=fee_alloc,
                        tax=tax_alloc,
                        net_pnl=net,
                        hold_seconds=hold_seconds,
                    )
                )
                buy_fill.qty -= match_qty
                sell_qty_left -= match_qty
                if buy_fill.qty <= 0:
                    fifo.pop(0)
            if sell_qty_left > 0:
                logger.warning("[REPORT] sell qty exceeds buys: code=%s qty=%s", code, sell_qty_left)
        if include_open and fifo:
            for buy_fill in fifo:
                gross = 0
                closed.append(
                    ClosedLot(
                        code=code,
                        name=buy_fill.name,
                        entry_ts=buy_fill.ts,
                        exit_ts=buy_fill.ts,
                        entry_price=buy_fill.price,
                        exit_price=buy_fill.price,
                        qty=buy_fill.qty,
                        gross_pnl=gross,
                        fee=0,
                        tax=0,
                        net_pnl=0,
                        hold_seconds=0,
                    )
                )
    return closed


def summarize_by_symbol(closed_lots: Iterable[ClosedLot]) -> List[SymbolPerf]:
    grouped: Dict[str, List[ClosedLot]] = {}
    for lot in closed_lots:
        grouped.setdefault(lot.code, []).append(lot)
    results: List[SymbolPerf] = []
    for code, lots in grouped.items():
        wins = sum(1 for lot in lots if lot.net_pnl > 0)
        losses = sum(1 for lot in lots if lot.net_pnl < 0)
        closed_trades = len(lots)
        win_rate = (wins / closed_trades * 100) if closed_trades else 0.0
        buy_amount = sum(lot.entry_price * lot.qty for lot in lots)
        sell_amount = sum(lot.exit_price * lot.qty for lot in lots)
        gross_profit_sum = sum(lot.gross_pnl for lot in lots if lot.gross_pnl > 0)
        gross_loss_sum = sum(lot.gross_pnl for lot in lots if lot.gross_pnl < 0)
        net_pnl_sum = sum(lot.net_pnl for lot in lots)
        return_pct = (net_pnl_sum / buy_amount * 100) if buy_amount else 0.0
        avg_win = (gross_profit_sum / wins) if wins else 0.0
        avg_loss = (gross_loss_sum / losses) if losses else 0.0
        avg_pnl = (net_pnl_sum / closed_trades) if closed_trades else 0.0
        profit_factor = (
            gross_profit_sum / abs(gross_loss_sum) if gross_loss_sum < 0 else 0.0
        )
        avg_hold_minutes = (
            sum(lot.hold_seconds for lot in lots) / closed_trades / 60 if closed_trades else 0.0
        )
        fee_sum = sum(lot.fee for lot in lots)
        tax_sum = sum(lot.tax for lot in lots)
        name = lots[0].name if lots else None
        results.append(
            SymbolPerf(
                code=code,
                name=name,
                closed_trades=closed_trades,
                wins=wins,
                losses=losses,
                win_rate=win_rate,
                buy_amount=buy_amount,
                sell_amount=sell_amount,
                gross_profit_sum=gross_profit_sum,
                gross_loss_sum=gross_loss_sum,
                net_pnl_sum=net_pnl_sum,
                return_pct=return_pct,
                avg_win=avg_win,
                avg_loss=avg_loss,
                avg_pnl=avg_pnl,
                profit_factor=profit_factor,
                avg_hold_minutes=avg_hold_minutes,
                fee_sum=fee_sum,
                tax_sum=tax_sum,
            )
        )
    return results


def summarize_daily(closed_lots: Iterable[ClosedLot], bucket_minutes: int = 30) -> DailyPerf:
    lots = list(closed_lots)
    if not lots:
        return DailyPerf(
            date="",
            total_closed_trades=0,
            wins=0,
            losses=0,
            win_rate=0.0,
            net_pnl_sum=0,
            gross_pnl_sum=0,
            fee_sum=0,
            tax_sum=0,
            avg_pnl=0.0,
            best_trade=None,
            worst_trade=None,
            best_symbol=None,
            worst_symbol=None,
            time_bucket_perf=[],
        )
    date = lots[0].exit_ts.date().isoformat()
    total = len(lots)
    wins = sum(1 for lot in lots if lot.net_pnl > 0)
    losses = sum(1 for lot in lots if lot.net_pnl < 0)
    win_rate = wins / total * 100 if total else 0.0
    net_pnl_sum = sum(lot.net_pnl for lot in lots)
    gross_pnl_sum = sum(lot.gross_pnl for lot in lots)
    fee_sum = sum(lot.fee for lot in lots)
    tax_sum = sum(lot.tax for lot in lots)
    avg_pnl = net_pnl_sum / total if total else 0.0
    best_trade = max(lots, key=lambda lot: lot.net_pnl, default=None)
    worst_trade = min(lots, key=lambda lot: lot.net_pnl, default=None)

    symbol_pnl: Dict[str, int] = {}
    for lot in lots:
        symbol_pnl[lot.code] = symbol_pnl.get(lot.code, 0) + lot.net_pnl
    best_symbol = max(symbol_pnl, key=symbol_pnl.get) if symbol_pnl else None
    worst_symbol = min(symbol_pnl, key=symbol_pnl.get) if symbol_pnl else None

    buckets: Dict[str, dict] = {}
    for lot in lots:
        bucket_start = lot.exit_ts.replace(minute=(lot.exit_ts.minute // bucket_minutes) * bucket_minutes, second=0)
        bucket_label = bucket_start.strftime("%H:%M")
        bucket = buckets.setdefault(
            bucket_label,
            {"bucket": bucket_label, "trades": 0, "wins": 0, "losses": 0, "net_pnl": 0},
        )
        bucket["trades"] += 1
        if lot.net_pnl > 0:
            bucket["wins"] += 1
        elif lot.net_pnl < 0:
            bucket["losses"] += 1
        bucket["net_pnl"] += lot.net_pnl
    bucket_perf = []
    for bucket in sorted(buckets.values(), key=lambda x: x["bucket"]):
        trades = bucket["trades"]
        win_rate_bucket = bucket["wins"] / trades * 100 if trades else 0.0
        bucket_perf.append(
            {
                "bucket": bucket["bucket"],
                "trades": trades,
                "win_rate": win_rate_bucket,
                "net_pnl": bucket["net_pnl"],
            }
        )

    return DailyPerf(
        date=date,
        total_closed_trades=total,
        wins=wins,
        losses=losses,
        win_rate=win_rate,
        net_pnl_sum=net_pnl_sum,
        gross_pnl_sum=gross_pnl_sum,
        fee_sum=fee_sum,
        tax_sum=tax_sum,
        avg_pnl=avg_pnl,
        best_trade=best_trade,
        worst_trade=worst_trade,
        best_symbol=best_symbol,
        worst_symbol=worst_symbol,
        time_bucket_perf=bucket_perf,
    )
