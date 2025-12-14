+"""Dummy Kiwoom client that mirrors the production interface.
+
+This module keeps the function signatures that will later be wired to the
+real Kiwoom REST API. For now every call only logs what would happen.
+"""
+from __future__ import annotations
+
+import logging
+from dataclasses import dataclass
+from typing import Dict
+
+logger = logging.getLogger(__name__)
+
+
+@dataclass
+class OrderResult:
+    """Simple order result placeholder returned by KiwoomClient."""
+
+    symbol: str
+    quantity: int
+    price: float
+    status: str
+    message: str = ""
+
+
+class KiwoomClient:
+    """Dummy implementation of the Kiwoom REST client.
+
+    TODO: 실제 API 연동 시 구현
+    """
+
+    def __init__(self, account_no: str):
+        self.account_no = account_no
+
+    def send_buy_order(self, symbol: str, quantity: int, price: float) -> OrderResult:
+        logger.info("[REAL MODE] Would send buy order: %s x%d at %.2f", symbol, quantity, price)
+        return OrderResult(symbol=symbol, quantity=quantity, price=price, status="accepted")
+
+    def send_sell_order(self, symbol: str, quantity: int, price: float) -> OrderResult:
+        logger.info("[REAL MODE] Would send sell order: %s x%d at %.2f", symbol, quantity, price)
+        return OrderResult(symbol=symbol, quantity=quantity, price=price, status="accepted")
+
+    def get_current_price(self, symbol: str) -> float:
+        """Return a dummy current price for a symbol."""
+        # TODO: 실제 API 연동 시 구현
+        base = hash(symbol) % 100_000 / 100 + 10
+        return round(base, 2)
+
+    def get_account_summary(self) -> Dict[str, float]:
+        """Return placeholder account summary.
+
+        TODO: 실제 API 연동 시 구현
+        """
+        return {"cash": 0.0, "equity": 0.0, "pnl": 0.0}

