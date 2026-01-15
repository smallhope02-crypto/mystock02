from __future__ import annotations

from pathlib import Path

from src.trade_history_store import TradeHistoryStore


def test_trade_history_store_round_trip(tmp_path: Path) -> None:
    db_path = tmp_path / "trade_history.db"
    store = TradeHistoryStore(db_path=db_path)
    event = {
        "mode": "paper",
        "event_type": "paper_fill",
        "code": "005930",
        "side": "buy",
        "exec_price": 1000,
        "exec_qty": 1,
    }
    store.insert_event(event)
    rows = store.query_events("2000-01-01 00:00:00", "2100-01-01 00:00:00", mode="paper")
    assert rows
    assert rows[0]["code"] == "005930"
