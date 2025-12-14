+"""Paper trading broker that simulates fills and account state."""
+
+import logging
+from dataclasses import dataclass
+from typing import Dict
+
+logger = logging.getLogger(__name__)
+
+
+@dataclass
+class PaperOrderResult:
+    """Execution summary for paper trades."""
+
+    symbol: str
+    quantity: int
+    price: float
+    status: str
+    message: str = ""
+
+
+@dataclass
+class PaperPosition:
+    """Internal representation of a simulated position."""
+
+    symbol: str
+    quantity: int
+    average_price: float
+
+
+class PaperBroker:
+    """Lightweight in-memory broker for paper trading."""
+
+    def __init__(self, initial_cash: float = 1_000_000):
+        self.initial_cash = initial_cash
+        self.cash = initial_cash
+        self.positions: Dict[str, PaperPosition] = {}
+
+    def set_cash(self, cash: float) -> None:
+        self.initial_cash = float(cash)
+        self.cash = float(cash)
+        self.positions = {}
+        logger.info("Paper cash initialized to %.2f", self.cash)
+
+    def get_current_price(self, symbol: str) -> float:
+        """Return a deterministic pseudo-price for testing purposes."""
+        base = (hash(symbol) % 50_000) / 100 + 5
+        return round(base, 2)
+
+    def _ensure_position(self, symbol: str) -> PaperPosition:
+        if symbol not in self.positions:
+            self.positions[symbol] = PaperPosition(symbol=symbol, quantity=0, average_price=0.0)
+        return self.positions[symbol]
+
+    def send_buy_order(self, symbol: str, quantity: int, price: float) -> PaperOrderResult:
+        total_cost = quantity * price
+        if total_cost > self.cash:
+            affordable_qty = int(self.cash // price)
+            if affordable_qty < 1:
+                return PaperOrderResult(
+                    symbol=symbol, quantity=0, price=price, status="rejected", message="Insufficient cash"
+                )
+            quantity = affordable_qty
+            total_cost = quantity * price
+
+        self.cash -= total_cost
+        position = self._ensure_position(symbol)
+        new_total = position.quantity + quantity
+        if new_total > 0:
+            position.average_price = (
+                position.average_price * position.quantity + price * quantity
+            ) / new_total
+        position.quantity = new_total
+        logger.info("[PAPER] Bought %s x%d at %.2f", symbol, quantity, price)
+        return PaperOrderResult(symbol=symbol, quantity=quantity, price=price, status="filled")
+
+    def send_sell_order(self, symbol: str, quantity: int, price: float) -> PaperOrderResult:
+        position = self.positions.get(symbol)
+        if not position or position.quantity <= 0:
+            return PaperOrderResult(symbol=symbol, quantity=0, price=price, status="rejected", message="No position")
+
+        sell_qty = min(quantity, position.quantity)
+        proceeds = sell_qty * price
+        self.cash += proceeds
+        position.quantity -= sell_qty
+        if position.quantity == 0:
+            del self.positions[symbol]
+        logger.info("[PAPER] Sold %s x%d at %.2f", symbol, sell_qty, price)
+        return PaperOrderResult(symbol=symbol, quantity=sell_qty, price=price, status="filled")
+
+    def get_account_summary(self) -> Dict[str, float]:
+        equity = self.cash + sum(p.quantity * self.get_current_price(p.symbol) for p in self.positions.values())
+        pnl = equity - self.initial_cash
+        return {"cash": self.cash, "equity": equity, "pnl": pnl}
+
+    def get_positions(self) -> Dict[str, PaperPosition]:
+        return dict(self.positions)
