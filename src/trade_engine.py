+"""Trade engine coordinating selector, strategy, and broker layers."""
+
+import logging
+from typing import List
+
+from .kiwoom_client import KiwoomClient
+from .paper_broker import PaperBroker
+from .selector import UniverseSelector
+from .strategy import Order, Strategy
+
+logger = logging.getLogger(__name__)
+
+
+class TradeEngine:
+    """Run trading cycles using either the real client or the paper broker."""
+
+    def __init__(self, strategy: Strategy, selector: UniverseSelector, broker_mode: str = "paper"):
+        self.strategy = strategy
+        self.selector = selector
+        self.broker_mode = broker_mode
+        self.broker = self._build_broker()
+
+    def _build_broker(self):
+        if self.broker_mode == "real":
+            return KiwoomClient(account_no="00000000")
+        return PaperBroker(initial_cash=self.strategy.initial_cash)
+
+    def set_mode(self, mode: str) -> None:
+        if mode not in {"paper", "real"}:
+            raise ValueError("mode must be 'paper' or 'real'")
+        self.broker_mode = mode
+        self.broker = self._build_broker()
+
+    def set_paper_cash(self, cash: float) -> None:
+        if isinstance(self.broker, PaperBroker):
+            self.broker.set_cash(cash)
+            self.strategy.update_parameters(initial_cash=cash)
+
+    def _price_lookup(self, symbol: str) -> float:
+        return self.broker.get_current_price(symbol)
+
+    def run_once(self, condition_name: str) -> None:
+        """Execute one scan/evaluation cycle."""
+        universe = self.selector.select(condition_name)
+
+        exit_orders = self.strategy.evaluate_exit(self._price_lookup)
+        self._execute_orders(exit_orders)
+
+        entry_orders = self.strategy.evaluate_entry(universe, self._price_lookup)
+        self._execute_orders(entry_orders)
+
+    def _execute_orders(self, orders: List[Order]) -> None:
+        for order in orders:
+            if order.side == "buy":
+                result = self.broker.send_buy_order(order.symbol, order.quantity, order.price)
+            else:
+                result = self.broker.send_sell_order(order.symbol, order.quantity, order.price)
+
+            filled_qty = getattr(result, "quantity", 0)
+            fill_price = getattr(result, "price", order.price)
+            self.strategy.register_fill(order, filled_qty, fill_price)
+            logger.info("Executed %s %s x%d at %.2f (%s)", order.side, order.symbol, filled_qty, fill_price, result.status)
+
+    def account_summary(self):
+        if hasattr(self.broker, "get_account_summary"):
+            return self.broker.get_account_summary()
+        return self.strategy.snapshot()
