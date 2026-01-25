from datetime import datetime, timedelta

from src.performance_analyzer import Fill
from src.performance_modes import WinLossMode, build_trade_units, summarize_by_symbol_units


def _dt(minutes: int) -> datetime:
    return datetime(2024, 1, 2, 9, 0, 0) + timedelta(minutes=minutes)


def test_round_trip_units() -> None:
    fills = [
        Fill(ts=_dt(0), mode="paper", code="0001", name="AAA", side="buy", price=1000, qty=10),
        Fill(ts=_dt(5), mode="paper", code="0001", name="AAA", side="sell", price=1100, qty=10),
    ]
    units = build_trade_units(fills, WinLossMode.ROUND_TRIP)
    assert len(units) == 1
    unit = units[0]
    assert unit.net_pnl == 1000


def test_sell_fill_units_fifo_cost() -> None:
    fills = [
        Fill(ts=_dt(0), mode="paper", code="0001", name="AAA", side="buy", price=1000, qty=5),
        Fill(ts=_dt(1), mode="paper", code="0001", name="AAA", side="buy", price=1100, qty=5),
        Fill(ts=_dt(2), mode="paper", code="0001", name="AAA", side="sell", price=1200, qty=6),
        Fill(ts=_dt(3), mode="paper", code="0001", name="AAA", side="sell", price=900, qty=4),
    ]
    units = build_trade_units(fills, WinLossMode.SELL_FILL)
    assert len(units) == 2
    assert units[0].qty == 6
    assert units[0].entry_price == 1017
    assert units[1].qty == 4


def test_summarize_units_win_rate() -> None:
    fills = [
        Fill(ts=_dt(0), mode="paper", code="0001", name="AAA", side="buy", price=1000, qty=1),
        Fill(ts=_dt(1), mode="paper", code="0001", name="AAA", side="sell", price=1100, qty=1),
        Fill(ts=_dt(2), mode="paper", code="0001", name="AAA", side="buy", price=1000, qty=1),
        Fill(ts=_dt(3), mode="paper", code="0001", name="AAA", side="sell", price=900, qty=1),
    ]
    units = build_trade_units(fills, WinLossMode.ROUND_TRIP)
    summary = summarize_by_symbol_units(units)
    assert summary[0].win_rate == 50.0
