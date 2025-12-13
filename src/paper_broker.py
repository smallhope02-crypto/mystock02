+"""Paper trading broker that simulates fills and balances locally."""
+
+from __future__ import annotations
+
+import logging
+import random
+from dataclasses import dataclass, field
+from typing import Dict
+
+logger = logging.getLogger(__name__)
+
+
+@dataclass
+class PaperPosition:
+    symbol: str
+    quantity: int
+    avg_price: float
+
+
+@dataclass
+class PaperBroker:
+    """Lightweight simulator for paper trading.
+
+    The broker mirrors the method names of :class:`~src.kiwoom_client.KiwoomClient`
+    to allow seamless swapping in :class:`~src.trade_engine.TradeEngine`.
+    """
+
+    initial_cash: float = 10_000_000.0
+    cash: float = field(init=False)
+    positions: Dict[str, PaperPosition] = field(default_factory=dict, init=False)
+
+    def __post_init__(self) -> None:
+        self.cash = float(self.initial_cash)
+        logger.info("[PaperBroker] Initialized with cash=%s", self.cash)
+
+    def reset_cash(self, cash: float) -> None:
+        """Reset the virtual balance and clear positions."""
+
+        logger.info("[PaperBroker] Resetting cash to %s", cash)
+        self.initial_cash = float(cash)
+        self.cash = float(cash)
+        self.positions.clear()
+
+    def get_current_price(self, symbol: str) -> float:
+        """Return a pseudo-random price for simulation purposes."""
+
+        price = round(random.uniform(10000, 80000), 2)
+        logger.debug("[PaperBroker] price for %s -> %s", symbol, price)
+        return price
+
+    def send_buy_order(self, symbol: str, quantity: int, price: float) -> dict:
+        """Simulate a marketable buy order.
+
+        The order is partially filled when cash is insufficient. The fill is
+        assumed immediate for simplicity.
+        """
+
+        max_affordable = int(self.cash // price)
+        filled_qty = min(quantity, max_affordable)
+        if filled_qty <= 0:
+            logger.warning("[PaperBroker] Reject BUY %s x%s @ %s (insufficient cash)", symbol, quantity, price)
+            return {"status": "rejected", "filled_qty": 0, "avg_price": price}
+
+        cost = filled_qty * price
+        self.cash -= cost
+        position = self.positions.get(symbol)
+        if position:
+            total_cost = position.avg_price * position.quantity + cost
+            total_qty = position.quantity + filled_qty
+            avg_price = total_cost / total_qty
+            position.quantity = total_qty
+            position.avg_price = avg_price
+        else:
+            self.positions[symbol] = PaperPosition(symbol=symbol, quantity=filled_qty, avg_price=price)
+        logger.info(
+            "[PaperBroker] BUY filled %s x%s @ %s (cost=%s, cash=%s)",
+            symbol,
+            filled_qty,
+            price,
+            cost,
+            self.cash,
+        )
+        return {"status": "filled", "filled_qty": filled_qty, "avg_price": price}
+
+    def send_sell_order(self, symbol: str, quantity: int, price: float) -> dict:
+        """Simulate a sell order for held positions."""
+
+        position = self.positions.get(symbol)
+        if not position or position.quantity <= 0:
+            logger.warning("[PaperBroker] Reject SELL %s x%s @ %s (no position)", symbol, quantity, price)
+            return {"status": "rejected", "filled_qty": 0, "avg_price": price}
+
+        filled_qty = min(quantity, position.quantity)
+        proceeds = filled_qty * price
+        position.quantity -= filled_qty
+        self.cash += proceeds
+        if position.quantity == 0:
+            del self.positions[symbol]
+        logger.info(
+            "[PaperBroker] SELL filled %s x%s @ %s (proceeds=%s, cash=%s)",
+            symbol,
+            filled_qty,
+            price,
+            proceeds,
+            self.cash,
+        )
+        return {"status": "filled", "filled_qty": filled_qty, "avg_price": price}
+
+    def get_positions(self) -> Dict[str, PaperPosition]:
+        """Return a copy of current positions."""
+
+        return {k: PaperPosition(v.symbol, v.quantity, v.avg_price) for k, v in self.positions.items()}
+
+    def summary(self) -> dict:
+        """Provide a quick account snapshot for the GUI."""
+
+        portfolio_value = sum(pos.quantity * self.get_current_price(pos.symbol) for pos in self.positions.values())
+        total_equity = self.cash + portfolio_value
+        profit_loss_pct = 0.0
+        if self.initial_cash:
+            profit_loss_pct = ((total_equity - self.initial_cash) / self.initial_cash) * 100
+        return {
+            "cash": self.cash,
+            "portfolio_value": portfolio_value,
+            "total_equity": total_equity,
+            "profit_loss_pct": profit_loss_pct,
+        }
