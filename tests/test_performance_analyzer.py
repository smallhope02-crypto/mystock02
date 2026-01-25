from datetime import datetime, timedelta

from src.performance_analyzer import Fill, build_closed_lots, summarize_by_symbol


def _dt(minutes: int) -> datetime:
    return datetime(2024, 1, 2, 9, 0, 0) + timedelta(minutes=minutes)


def test_build_closed_lots_single_round_trip() -> None:
    fills = [
        Fill(ts=_dt(0), mode="paper", code="0001", name="AAA", side="buy", price=1000, qty=10),
        Fill(ts=_dt(10), mode="paper", code="0001", name="AAA", side="sell", price=1100, qty=10),
    ]
    closed = build_closed_lots(fills)
    assert len(closed) == 1
    lot = closed[0]
    assert lot.gross_pnl == 1000
    assert lot.net_pnl == 1000
    assert lot.qty == 10


def test_build_closed_lots_partial_fills_fifo() -> None:
    fills = [
        Fill(ts=_dt(0), mode="paper", code="0001", name="AAA", side="buy", price=1000, qty=5),
        Fill(ts=_dt(1), mode="paper", code="0001", name="AAA", side="buy", price=1020, qty=5),
        Fill(ts=_dt(5), mode="paper", code="0001", name="AAA", side="sell", price=1100, qty=6),
        Fill(ts=_dt(6), mode="paper", code="0001", name="AAA", side="sell", price=900, qty=4),
    ]
    closed = build_closed_lots(fills)
    assert len(closed) == 3
    first = closed[0]
    assert first.entry_price == 1000
    assert first.exit_price == 1100
    assert first.qty == 5
    second = closed[1]
    assert second.entry_price == 1020
    assert second.exit_price == 1100
    assert second.qty == 1
    third = closed[2]
    assert third.entry_price == 1020
    assert third.exit_price == 900
    assert third.qty == 4


def test_summarize_by_symbol_metrics() -> None:
    fills = [
        Fill(ts=_dt(0), mode="paper", code="0001", name="AAA", side="buy", price=1000, qty=1),
        Fill(ts=_dt(1), mode="paper", code="0001", name="AAA", side="sell", price=1100, qty=1),
        Fill(ts=_dt(2), mode="paper", code="0001", name="AAA", side="buy", price=1000, qty=1),
        Fill(ts=_dt(3), mode="paper", code="0001", name="AAA", side="sell", price=900, qty=1),
    ]
    closed = build_closed_lots(fills)
    summary = summarize_by_symbol(closed)
    assert len(summary) == 1
    perf = summary[0]
    assert perf.closed_trades == 2
    assert perf.wins == 1
    assert perf.losses == 1
    assert perf.net_pnl_sum == 0
    assert perf.profit_factor == 1.0
