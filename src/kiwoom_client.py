+"""Dummy Kiwoom REST client facade.
+
+The class mirrors methods that a real broker client would expose so that the
+rest of the application can remain stable while swapping in the production
+implementation later.
+"""
+
+from __future__ import annotations
+
+import logging
+import random
+from typing import Dict
+
+logger = logging.getLogger(__name__)
+
+
+class KiwoomClient:
+    """Placeholder Kiwoom client for live-trading mode.
+
+    TODO: 실제 키움 REST API 연동 시, 인증 토큰 관리와 실제 주문/시세 조회 로직을 구현합니다.
+    """
+
+    def __init__(self) -> None:
+        self._positions: Dict[str, int] = {}
+
+    def get_current_price(self, symbol: str) -> float:
+        """Fetch the latest price for ``symbol``.
+
+        The dummy implementation returns a pseudo-random price so that the
+        rest of the application can simulate behavior without contacting the
+        real API.
+        """
+
+        price = round(random.uniform(10000, 80000), 2)
+        logger.debug("[KiwoomClient] price for %s -> %s", symbol, price)
+        return price
+
+    def send_buy_order(self, symbol: str, quantity: int, price: float) -> dict:
+        """Pretend to submit a buy order.
+
+        In live-trading mode we only log the request to prevent accidental real
+        trades while still keeping the call-site stable.
+        """
+
+        logger.info("[KiwoomClient] BUY %s x%s @ %s (demo only)", symbol, quantity, price)
+        self._positions[symbol] = self._positions.get(symbol, 0) + quantity
+        return {
+            "status": "submitted",
+            "filled_qty": quantity,
+            "avg_price": price,
+        }
+
+    def send_sell_order(self, symbol: str, quantity: int, price: float) -> dict:
+        """Pretend to submit a sell order.
+
+        The dummy simply logs and assumes the order was fully filled.
+        """
+
+        logger.info("[KiwoomClient] SELL %s x%s @ %s (demo only)", symbol, quantity, price)
+        current = self._positions.get(symbol, 0)
+        self._positions[symbol] = max(0, current - quantity)
+        return {
+            "status": "submitted",
+            "filled_qty": quantity,
+            "avg_price": price,
+        }
+
+    def get_positions(self) -> Dict[str, int]:
+        """Return the cached dummy positions."""
+
+        return dict(self._positions)
