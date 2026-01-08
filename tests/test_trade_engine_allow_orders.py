from src.strategy import Strategy
from src.trade_engine import TradeEngine
from src.selector import UniverseSelector


class DummySelector(UniverseSelector):
    def __init__(self, symbols):
        self._symbols = symbols

    def select(self, condition_name: str):  # pragma: no cover - interface compliance
        return list(self._symbols)


def test_run_once_skips_orders_when_disallowed():
    strategy = Strategy(initial_cash=10_000, max_positions=1)
    selector = DummySelector(["000001"])
    engine = TradeEngine(strategy=strategy, selector=selector, broker_mode="paper")
    engine._entry_price_lookup = lambda _s: 100

    engine.run_once("t", allow_orders=False)
    assert not strategy.positions


def test_run_once_executes_when_allowed():
    strategy = Strategy(initial_cash=10_000, max_positions=1)
    selector = DummySelector(["000001"])
    engine = TradeEngine(strategy=strategy, selector=selector, broker_mode="paper")
    engine._entry_price_lookup = lambda _s: 100

    engine.run_once("t", allow_orders=True)
    assert "000001" in strategy.positions
