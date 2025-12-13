+"""Trading strategy primitives and evaluation logic."""
+
+from __future__ import annotations
+
+import logging
+from dataclasses import dataclass, field
+from typing import Dict, List, Optional
+
+logger = logging.getLogger(__name__)
+
+
+@dataclass
+class Position:
+    symbol: str
+    quantity: int
+    entry_price: float
+
+    def market_value(self, price: float) -> float:
+        return self.quantity * price
+
+
+@dataclass
+class Order:
+    symbol: str
+    side: str
+    quantity: int
+    price: float
+
+
+@dataclass
+class StrategyParameters:
+    max_positions: int = 5
+    initial_cash: float = 10_000_000.0
+    take_profit_pct: float = 0.03
+    stop_loss_pct: float = -0.02
+
+
+@dataclass
+class Strategy:
+    """Encapsulates entry/exit logic and local cash tracking."""
+
+    parameters: StrategyParameters = field(default_factory=StrategyParameters)
+    cash: float = field(init=False)
+    positions: Dict[str, Position] = field(default_factory=dict, init=False)
+
+    def __post_init__(self) -> None:
+        self.cash = float(self.parameters.initial_cash)
+
+    def update_parameters(self, **kwargs) -> None:
+        """Update strategy parameters and adjust cash if provided."""
+
+        for key, value in kwargs.items():
+            if hasattr(self.parameters, key):
+                setattr(self.parameters, key, value)
+        if "initial_cash" in kwargs:
+            self.cash = float(self.parameters.initial_cash)
+            self.positions.clear()
+            logger.info("[Strategy] Reset cash to %s and cleared positions", self.cash)
+
+    def evaluate_entry(self, symbol: str, price: float, broker) -> Optional[Order]:
+        """Decide whether to enter a position.
+
+        - Respects ``max_positions`` limit.
+        - Allocates budget equally across remaining slots.
+        - Skips orders that would buy fewer than 1 share.
+        """
+
+        if len(self.positions) >= self.parameters.max_positions:
+            logger.debug("[Strategy] Max positions reached, skipping %s", symbol)
+            return None
+
+        remaining_slots = self.parameters.max_positions - len(self.positions)
+        budget_per_symbol = self.cash / remaining_slots if remaining_slots else 0
+        quantity = int(budget_per_symbol // price)
+        if quantity < 1:
+            logger.debug("[Strategy] Insufficient budget for %s (price=%s, cash=%s)", symbol, price, self.cash)
+            return None
+
+        logger.info(
+            "[Strategy] Attempting entry %s x%s @ %s (budget_per_symbol=%s)",
+            symbol,
+            quantity,
+            price,
+            budget_per_symbol,
+        )
+        result = broker.send_buy_order(symbol, quantity, price)
+        filled_qty = result.get("filled_qty", 0)
+        avg_price = result.get("avg_price", price)
+        if filled_qty <= 0:
+            logger.info("[Strategy] Order for %s rejected by broker", symbol)
+            return None
+
+        cost = filled_qty * avg_price
+        self.cash -= cost
+        self.positions[symbol] = Position(symbol=symbol, quantity=filled_qty, entry_price=avg_price)
+        logger.info("[Strategy] Entered %s x%s @ %s, cash=%s", symbol, filled_qty, avg_price, self.cash)
+        return Order(symbol=symbol, side="BUY", quantity=filled_qty, price=avg_price)
+
+    def evaluate_exit(self, symbol: str, price: float, broker) -> Optional[Order]:
+        """Check exit conditions and close positions if needed."""
+
+        position = self.positions.get(symbol)
+        if not position:
+            return None
+
+        profit_pct = (price - position.entry_price) / position.entry_price
+        if profit_pct >= self.parameters.take_profit_pct or profit_pct <= self.parameters.stop_loss_pct:
+            result = broker.send_sell_order(symbol, position.quantity, price)
+            filled_qty = result.get("filled_qty", 0)
+            avg_price = result.get("avg_price", price)
+            if filled_qty <= 0:
+                logger.info("[Strategy] Exit for %s rejected by broker", symbol)
+                return None
+            proceeds = filled_qty * avg_price
+            self.cash += proceeds
+            logger.info("[Strategy] Exited %s x%s @ %s, cash=%s", symbol, filled_qty, avg_price, self.cash)
+            del self.positions[symbol]
+            return Order(symbol=symbol, side="SELL", quantity=filled_qty, price=avg_price)
+        return None
+
+    def open_positions(self) -> List[Position]:
+        return list(self.positions.values())
