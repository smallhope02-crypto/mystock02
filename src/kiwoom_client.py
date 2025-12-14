"""Dummy Kiwoom client that mirrors the production interface.

This module keeps the function signatures that will later be wired to the
real Kiwoom REST API. For now every call only logs what would happen.
"""

import logging
from dataclasses import dataclass
from typing import Dict, List

from .config import AppConfig

logger = logging.getLogger(__name__)


@dataclass
class OrderResult:
    """Simple order result placeholder returned by KiwoomClient."""

    symbol: str
    quantity: int
    price: float
    status: str
    message: str = ""


class KiwoomClient:
    """Dummy implementation of the Kiwoom REST client.

    TODO: 실제 API 연동 시 구현
    """

    def __init__(self, account_no: str, app_key: str = "", app_secret: str = ""):
        self.account_no = account_no
        self.app_key = app_key
        self.app_secret = app_secret
        self._connected_paper = False
        self._connected_real = False

    def update_credentials(self, config: AppConfig) -> None:
        """Replace API credentials in memory.

        The GUI can call this instead of mutating environment variables.
        """

        self.account_no = config.account_no
        self.app_key = config.app_key
        self.app_secret = config.app_secret

    def login_paper(self) -> bool:
        """Simulate a paper-server login.

        TODO: 실제 API 연동 시 구현
        """

        self._connected_paper = True
        logger.info("[REAL MODE] Simulated paper login for account %s", self.account_no)
        return self._connected_paper

    def login_real(self) -> bool:
        """Simulate a real-server login.

        TODO: 실제 API 연동 시 구현
        """

        self._connected_real = True
        logger.info("[REAL MODE] Simulated real login for account %s", self.account_no)
        return self._connected_real

    def is_connected_paper(self) -> bool:
        return self._connected_paper

    def is_connected_real(self) -> bool:
        return self._connected_real

    def get_balance_paper(self) -> Dict[str, float]:
        """Return placeholder paper-account balance.

        TODO: 실제 API 연동 시 구현. GUI에서는 PaperBroker와 연결하여 표시.
        """

        return {"cash": 0.0}

    def get_balance_real(self) -> Dict[str, float]:
        """Return placeholder real-account balance.

        TODO: 실제 API 연동 시 구현
        """

        return {"cash": 1_000_000}

    def get_condition_list(self) -> List[str]:
        """Return a dummy condition list.

        TODO: 실제 API 연동 시 구현 (키움 조건식 조회 API 호출)
        """

        return ["단기급등_체크", "테스트_조건1", "수급_모니터", "뉴스_키워드"]

    def send_buy_order(self, symbol: str, quantity: int, price: float) -> OrderResult:
        logger.info("[REAL MODE] Would send buy order: %s x%d at %.2f", symbol, quantity, price)
        return OrderResult(symbol=symbol, quantity=quantity, price=price, status="accepted")

    def send_sell_order(self, symbol: str, quantity: int, price: float) -> OrderResult:
        logger.info("[REAL MODE] Would send sell order: %s x%d at %.2f", symbol, quantity, price)
        return OrderResult(symbol=symbol, quantity=quantity, price=price, status="accepted")

    def get_current_price(self, symbol: str) -> float:
        """Return a dummy current price for a symbol."""
        # TODO: 실제 API 연동 시 구현
        base = hash(symbol) % 100_000 / 100 + 10
        return round(base, 2)

    def get_account_summary(self) -> Dict[str, float]:
        """Return placeholder account summary.

        TODO: 실제 API 연동 시 구현
        """

        return {"cash": 0.0, "equity": 0.0, "pnl": 0.0}
