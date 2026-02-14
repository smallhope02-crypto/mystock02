from src.kiwoom_client import KiwoomClient
from src.paper_broker import PaperBroker
from src.selector import UniverseSelector
from src.strategy import Strategy
from src.trade_engine import TradeEngine


def test_limit_entry_price_uses_shifted_ticks():
    strategy = Strategy(initial_cash=10_000, max_positions=1)
    client = KiwoomClient(account_no="0000")
    selector = UniverseSelector(client)
    broker = PaperBroker(initial_cash=10_000)
    engine = TradeEngine(strategy, selector, broker_mode="paper", kiwoom_client=client, paper_broker=broker)
    engine.set_buy_pricing("limit", 5)
    client._last_prices["0001"] = 1_990
    engine.set_external_universe(["0001"])

    engine.run_once("test", allow_orders=True)

    assert "0001" in strategy.positions
    assert strategy.positions["0001"].entry_price == 1_995
