"""Win/loss definition modes for performance reporting."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Dict, Iterable, List, Optional

from .performance_analyzer import Fill, ClosedLot, build_closed_lots

logger = logging.getLogger(__name__)


class WinLossMode(str, Enum):
    ROUND_TRIP = "round_trip"
    SELL_FILL = "sell_fill"


@dataclass
class TradeUnit:
    code: str
    name: Optional[str]
    entry_ts: Optional[datetime]
    exit_ts: datetime
    qty: int
    entry_price: Optional[int]
    exit_price: int
    gross_pnl: int
    fee: int
    tax: int
    net_pnl: int
    hold_seconds: Optional[int]
    unit_type: str
    ref: Optional[str]


@dataclass
class SymbolUnitPerf:
    code: str
    name: Optional[str]
    trades: int
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
    avg_hold_minutes: Optional[float]
    fee_sum: int
    tax_sum: int


@dataclass
class DailyUnitPerf:
    date: str
    total_trades: int
    wins: int
    losses: int
    win_rate: float
    net_pnl_sum: int
    gross_pnl_sum: int
    fee_sum: int
    tax_sum: int
    avg_pnl: float
    best_trade: Optional[TradeUnit]
    worst_trade: Optional[TradeUnit]
    best_symbol: Optional[str]
    worst_symbol: Optional[str]
    time_bucket_perf: List[dict]


def build_trade_units(fills: Iterable[Fill], mode: WinLossMode) -> List[TradeUnit]:
    if mode == WinLossMode.ROUND_TRIP:
        closed = build_closed_lots(fills)
        units: List[TradeUnit] = []
        for lot in closed:
            units.append(
                TradeUnit(
                    code=lot.code,
                    name=lot.name,
                    entry_ts=lot.entry_ts,
                    exit_ts=lot.exit_ts,
                    qty=lot.qty,
                    entry_price=lot.entry_price,
                    exit_price=lot.exit_price,
                    gross_pnl=lot.gross_pnl,
                    fee=lot.fee,
                    tax=lot.tax,
                    net_pnl=lot.net_pnl,
                    hold_seconds=lot.hold_seconds,
                    unit_type="round_trip",
                    ref=None,
                )
            )
        return units

    if mode != WinLossMode.SELL_FILL:
        return []

    by_code: Dict[str, List[Fill]] = {}
    for fill in fills:
        by_code.setdefault(fill.code, []).append(fill)

    units: List[TradeUnit] = []
    for code, items in by_code.items():
        items.sort(key=lambda f: f.ts)
        fifo: List[Fill] = []
        for fill in items:
            if fill.side == "buy":
                fifo.append(fill)
                continue
            if fill.side != "sell":
                continue
            if not fifo:
                logger.warning("[REPORT] sell before buy: code=%s ts=%s", code, fill.ts.isoformat())
                continue
            sell_qty_left = fill.qty
            fee_left = fill.fee
            tax_left = fill.tax
            matched_qty = 0
            cost_sum = 0
            entry_ts = None
            while sell_qty_left > 0 and fifo:
                buy_fill = fifo[0]
                if entry_ts is None:
                    entry_ts = buy_fill.ts
                match_qty = min(buy_fill.qty, sell_qty_left)
                if match_qty <= 0:
                    fifo.pop(0)
                    continue
                matched_qty += match_qty
                cost_sum += buy_fill.price * match_qty
                buy_fill.qty -= match_qty
                sell_qty_left -= match_qty
                if buy_fill.qty <= 0:
                    fifo.pop(0)
            if matched_qty <= 0:
                continue
            if sell_qty_left > 0:
                logger.warning("[REPORT] sell qty exceeds buys: code=%s qty=%s", code, sell_qty_left)

            avg_entry = int(round(cost_sum / matched_qty))
            gross = (fill.price - avg_entry) * matched_qty
            fee_alloc = fee_left if fee_left else 0
            tax_alloc = tax_left if tax_left else 0
            net = gross - fee_alloc - tax_alloc
            hold_seconds = int((fill.ts - entry_ts).total_seconds()) if entry_ts else None
            units.append(
                TradeUnit(
                    code=code,
                    name=fill.name,
                    entry_ts=entry_ts,
                    exit_ts=fill.ts,
                    qty=matched_qty,
                    entry_price=avg_entry,
                    exit_price=fill.price,
                    gross_pnl=gross,
                    fee=fee_alloc,
                    tax=tax_alloc,
                    net_pnl=net,
                    hold_seconds=hold_seconds,
                    unit_type="sell_fill",
                    ref=fill.exec_no or fill.order_no,
                )
            )
    return units


def summarize_by_symbol_units(units: Iterable[TradeUnit]) -> List[SymbolUnitPerf]:
    grouped: Dict[str, List[TradeUnit]] = {}
    for unit in units:
        grouped.setdefault(unit.code, []).append(unit)

    results: List[SymbolUnitPerf] = []
    for code, lots in grouped.items():
        trades = len(lots)
        wins = sum(1 for lot in lots if lot.net_pnl > 0)
        losses = sum(1 for lot in lots if lot.net_pnl < 0)
        win_rate = wins / (wins + losses) * 100 if wins + losses else 0.0
        buy_amount = sum((lot.entry_price or 0) * lot.qty for lot in lots)
        sell_amount = sum(lot.exit_price * lot.qty for lot in lots)
        gross_profit_sum = sum(lot.gross_pnl for lot in lots if lot.gross_pnl > 0)
        gross_loss_sum = sum(lot.gross_pnl for lot in lots if lot.gross_pnl < 0)
        net_pnl_sum = sum(lot.net_pnl for lot in lots)
        return_pct = net_pnl_sum / buy_amount * 100 if buy_amount else 0.0
        avg_win = gross_profit_sum / wins if wins else 0.0
        avg_loss = gross_loss_sum / losses if losses else 0.0
        avg_pnl = net_pnl_sum / trades if trades else 0.0
        profit_factor = gross_profit_sum / abs(gross_loss_sum) if gross_loss_sum < 0 else 0.0
        hold_minutes = (
            sum(lot.hold_seconds or 0 for lot in lots) / trades / 60 if trades else None
        )
        fee_sum = sum(lot.fee for lot in lots)
        tax_sum = sum(lot.tax for lot in lots)
        name = lots[0].name if lots else None
        results.append(
            SymbolUnitPerf(
                code=code,
                name=name,
                trades=trades,
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
                avg_hold_minutes=hold_minutes,
                fee_sum=fee_sum,
                tax_sum=tax_sum,
            )
        )
    return results


def summarize_daily_units(units: Iterable[TradeUnit], bucket_minutes: int = 30) -> DailyUnitPerf:
    lots = list(units)
    if not lots:
        return DailyUnitPerf(
            date="",
            total_trades=0,
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
    win_rate = wins / (wins + losses) * 100 if wins + losses else 0.0
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
        bucket_start = lot.exit_ts.replace(
            minute=(lot.exit_ts.minute // bucket_minutes) * bucket_minutes, second=0
        )
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
        win_rate_bucket = bucket["wins"] / (bucket["wins"] + bucket["losses"]) * 100 if bucket["wins"] + bucket["losses"] else 0.0
        bucket_perf.append(
            {
                "bucket": bucket["bucket"],
                "trades": trades,
                "win_rate": win_rate_bucket,
                "net_pnl": bucket["net_pnl"],
            }
        )
    return DailyUnitPerf(
        date=date,
        total_trades=total,
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
