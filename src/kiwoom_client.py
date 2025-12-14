"""Dummy Kiwoom client that mirrors the production interface.

This module keeps the function signatures that will later be wired to the
real Kiwoom REST API. For now every call only logs what would happen.
"""

import logging
import sys
from dataclasses import dataclass
from typing import Dict, List, Tuple

from .config import AppConfig
from .kiwoom_openapi import KiwoomOpenAPI

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
        self._demo_balance = 1_000_000
        self.openapi: KiwoomOpenAPI | None = None
        self.use_openapi = False

    def attach_openapi(self, openapi: KiwoomOpenAPI) -> None:
        """Attach a GUI-hosted QAx Kiwoom control.

        The QAx control must be created after ``QApplication`` exists, so the GUI
        constructs it and injects it here rather than letting this client create
        it at import time.
        """

        self.openapi = openapi

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
        if self.openapi and sys.platform.startswith("win"):
            try:
                self.openapi.initialize_control()
                self.openapi.login()
            except Exception as exc:  # pragma: no cover - defensive guard for GUI layer
                logger.exception("OpenAPI connect failed: %s", exc)
                self.use_openapi = False
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

    def get_real_balance(self) -> int:
        """Return the cash balance for the configured real account.

        The actual Kiwoom REST/OpenAPI call should be implemented in
        :meth:`_fetch_balance_from_kiwoom_api`. This wrapper keeps exception
        handling in one place so GUI code can display a safe default instead
        of crashing.
        """

        try:
            return self._fetch_balance_from_kiwoom_api()
        except Exception as exc:  # pragma: no cover - defensive against API errors
            logger.exception("Failed to fetch real balance: %s", exc)
            return 0

    def _fetch_balance_from_kiwoom_api(self) -> int:
        """Placeholder for the real Kiwoom balance API call.

        TODO: 실제 API 연동 시 구현
        - 키움 REST/OpenAPI의 계좌 잔고 조회 엔드포인트를 호출
        - 응답 JSON/XML에서 예수금(현금성 잔고) 값을 파싱해 원 단위 정수로 반환
        - 필요 파라미터 예시: app_key, app_secret, account_no, access_token 등
        """

        # 더미 구현: 실제 호출 대신 고정 잔고를 반환합니다.
        return int(self._demo_balance)

    def get_balance_real(self) -> Dict[str, float]:
        """Legacy helper returning a dict-shaped real balance.

        GUI와 엔진 코드 호환성을 위해 남겨 두며, 내부적으로는
        :meth:`get_real_balance` 값을 감싸서 반환합니다.
        """

        return {"cash": float(self.get_real_balance())}

    def list_conditions(self) -> List[str]:
        """Return only condition names for backward compatibility."""

        return [name for _, name in self.get_condition_list()]

    def get_condition_list(self) -> List[Tuple[int, str]]:
        """Return (index, name) tuples for Kiwoom 0150 conditions.

        OpenAPI 사용 가능 시 :class:`KiwoomOpenAPI` 에서 파싱된 조건식을 그대로
        반환하고, 사용 불가 환경에서는 더미 조건식을 돌려줍니다.
        """

        self.use_openapi = bool(
            self.openapi and self.openapi.available and self.openapi.connected and sys.platform.startswith("win")
        )
        if self.use_openapi and self.openapi:
            try:
                parsed = self.openapi.get_conditions()
                if parsed:
                    return [(int(idx), name) for idx, name in parsed]
            except Exception as exc:  # pragma: no cover - optional path
                logger.exception("OpenAPI condition list failed: %s", exc)

        dummy_conditions: List[Tuple[int, str]] = [
            (0, "단기급등_체크"),
            (1, "돌파_추세"),
            (2, "장중급락_반등"),
        ]
        return dummy_conditions

    def get_condition_universe(self, condition_name: str) -> List[str]:
        """Return symbols matching the given condition name."""

        self.use_openapi = bool(
            self.openapi and self.openapi.available and self.openapi.connected and sys.platform.startswith("win")
        )
        if self.use_openapi and self.openapi:
            try:
                condition_index = next(
                    (idx for idx, name in self.openapi.get_conditions() if name == condition_name), None
                )
                if condition_index is not None:
                    return self.openapi.request_condition_universe(int(condition_index), condition_name)
            except Exception as exc:  # pragma: no cover - optional path
                logger.exception("OpenAPI condition universe failed: %s", exc)

        return ["005930", "000660", "035420", "068270", "035720"]

    def openapi_login_and_load_conditions(self) -> None:
        """Perform OpenAPI login and condition load sequence for the GUI."""

        if not self.openapi:
            self.use_openapi = False
            return
        self.openapi.initialize_control()
        if not self.openapi.is_enabled():
            self.use_openapi = False
            return
        self.openapi.connect_for_conditions()
        self.use_openapi = self.openapi.is_openapi_connected()
        if self.use_openapi:
            # 로그인 이벤트에서 조건 로딩을 시작하지만, 즉시 호출해도 안전하다.
            self.openapi.load_conditions()

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
