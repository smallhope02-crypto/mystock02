+"""Trade engine orchestrating selection, strategy decisions, and broker routing."""
+
+from __future__ import annotations
+
+import logging
+from typing import List, Optional
+
+from .kiwoom_client import KiwoomClient
+from .paper_broker import PaperBroker
+from .selector import UniverseSelector
+from .strategy import Strategy, StrategyParameters
+
+logger = logging.getLogger(__name__)
+
+
+class TradeEngine:
+    """High level coordinator tying together selector, strategy, and brokers."""
+
+    def __init__(
+        self,
+        mode: str = "paper",
+        initial_cash: float = 10_000_000.0,
+        max_positions: int = 5,
+    ) -> None:
+        self.selector = UniverseSelector()
+        self.live_client = KiwoomClient()
+        self.paper_broker = PaperBroker(initial_cash=initial_cash)
+        self.mode = mode
+        self.strategy = Strategy(StrategyParameters(max_positions=max_positions, initial_cash=initial_cash))
+        self._sync_cash_with_broker()
+
+    @property
+    def broker(self):
+        return self.paper_broker if self.mode == "paper" else self.live_client
+
+    def set_mode(self, mode: str, initial_cash: Optional[float] = None, max_positions: Optional[int] = None) -> None:
+        """Switch between paper and live modes."""
+
+        self.mode = mode
+        if initial_cash is not None:
+            self.strategy.update_parameters(initial_cash=initial_cash)
+            if mode == "paper":
+                self.paper_broker.reset_cash(initial_cash)
+        if max_positions is not None:
+            self.strategy.update_parameters(max_positions=max_positions)
+        logger.info("[TradeEngine] Mode set to %s", mode)
+        self._sync_cash_with_broker()
+
+    def _sync_cash_with_broker(self) -> None:
+        if self.mode == "paper":
+            self.strategy.cash = self.paper_broker.cash
+        logger.debug("[TradeEngine] Cash synchronized: %s", self.strategy.cash)
+
+    def run_once(self, condition_name: str) -> List[str]:
+        """Execute one iteration of selection and trading."""
+
+        signals = []
+        symbols = self.selector.select(condition_name)
+        # First evaluate exits for current positions
+        for position in list(self.strategy.positions.values()):
+            price = self._get_price(position.symbol)
+            order = self.strategy.evaluate_exit(position.symbol, price, self.broker)
+            if order:
+                signals.append(f"EXIT {order.symbol} {order.quantity} @ {order.price}")
+        # Then evaluate entries for new opportunities
+        for symbol in symbols:
+            if symbol in self.strategy.positions:
+                continue
+            price = self._get_price(symbol)
+            order = self.strategy.evaluate_entry(symbol, price, self.broker)
+            if order:
+                signals.append(f"ENTRY {order.symbol} {order.quantity} @ {order.price}")
+        self._sync_cash_with_broker()
+        return signals
+
+    def _get_price(self, symbol: str) -> float:
+        return self.broker.get_current_price(symbol)
+
+    def account_summary(self) -> dict:
+        if self.mode == "paper":
+            return self.paper_broker.summary()
+        # Live mode placeholder
+        equity = self.strategy.cash
+        return {"cash": self.strategy.cash, "portfolio_value": 0.0, "total_equity": equity, "profit_loss_pct": 0.0}
+
+    def positions_snapshot(self) -> List[dict]:
+        snapshot = []
+        for position in self.strategy.open_positions():
+            price = self._get_price(position.symbol)
+            snapshot.append(
+                {
+                    "symbol": position.symbol,
+                    "quantity": position.quantity,
+                    "entry_price": position.entry_price,
+                    "market_price": price,
+                    "market_value": position.market_value(price),
+                }
+            )
+        return snapshot
+
+
+def main() -> None:
+    """Small demo to show that the engine runs without the GUI."""
+
+    logging.basicConfig(level=logging.INFO)
+    engine = TradeEngine(mode="paper", initial_cash=5_000_000, max_positions=3)
+    signals = engine.run_once("demo_condition")
+    summary = engine.account_summary()
+    print("Signals", signals)
+    print("Summary", summary)
+
+
+if __name__ == "__main__":
+    main()
