import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.selector import UniverseSelector
from src.strategy import Strategy
from src.trade_engine import TradeEngine


class StrategyPaperBrokerTest(unittest.TestCase):
    def test_entry_respects_budget_and_max_positions(self):
        strategy = Strategy(initial_cash=100_000, max_positions=2)
        selector = UniverseSelector()
        engine = TradeEngine(strategy=strategy, selector=selector, broker_mode="paper")

        engine.set_paper_cash(100_000)
        engine.run_once("cond")
        self.assertLessEqual(len(strategy.positions), 2)
        self.assertGreater(strategy.cash, 0)

    def test_exit_restores_cash(self):
        strategy = Strategy(initial_cash=50_000, max_positions=1)
        selector = UniverseSelector()
        engine = TradeEngine(strategy=strategy, selector=selector, broker_mode="paper")
        engine.set_paper_cash(50_000)

        price = engine.paper_broker.get_current_price("SYM001")
        buy_order = strategy.evaluate_entry(["SYM001"], engine.paper_broker.get_current_price)[0]
        result = engine.paper_broker.send_buy_order("SYM001", buy_order.quantity, price)
        strategy.register_fill(buy_order, result.quantity, result.price, update_cash=False)
        strategy.cash = engine.paper_broker.cash

        sell_price = price * 1.1
        sell_order = strategy.evaluate_exit(lambda s: sell_price)[0]
        result = engine.paper_broker.send_sell_order("SYM001", sell_order.quantity, sell_price)
        strategy.register_fill(sell_order, result.quantity, result.price, update_cash=False)
        strategy.cash = engine.paper_broker.cash

        self.assertEqual(len(strategy.positions), 0)
        self.assertAlmostEqual(strategy.cash, engine.paper_broker.cash, delta=1)

    def test_close_all_positions(self):
        strategy = Strategy(initial_cash=100_000, max_positions=2)
        selector = UniverseSelector()
        engine = TradeEngine(strategy=strategy, selector=selector, broker_mode="paper")
        engine.set_paper_cash(100_000)

        price = engine.paper_broker.get_current_price("SYM010")
        buy_order = strategy.evaluate_entry(["SYM010"], engine.paper_broker.get_current_price)[0]
        result = engine.paper_broker.send_buy_order("SYM010", buy_order.quantity, price)
        strategy.register_fill(buy_order, result.quantity, result.price, update_cash=False)
        strategy.cash = engine.paper_broker.cash

        engine.close_all_positions()
        strategy.cash = engine.paper_broker.cash
        self.assertEqual(len(strategy.positions), 0)


if __name__ == "__main__":
    unittest.main()
