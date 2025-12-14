"""Dummy Kiwoom client that mirrors the production interface.

This module keeps the function signatures that will later be wired to the
real Kiwoom REST API. For now every call only logs what would happen.
"""

import logging
import sys
from dataclasses import dataclass
from typing import Dict, List

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
        self.openapi = KiwoomOpenAPI()
        self.use_openapi = False

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
        if self.openapi.available and sys.platform.startswith("win"):
            try:
                self.openapi.connect()
                self.use_openapi = self.openapi.is_connected()
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
        """Return condition names stored in Kiwoom.

        When OpenAPI is available (Windows + KHOpenAPI installed) this calls
        :class:`KiwoomOpenAPI` to load and parse the 0150 조건식 목록. The
        current demo implementation falls back to dummy values when running in
        CI or non-Windows environments.

        TODO: 실제 API 연동 시 구현
        - 필요 파라미터 예시: app_key, app_secret, account_no, access_token 등
        - 응답 데이터에서 조건식 이름 배열을 추출해 리스트로 변환
        - OpenAPI 환경에서는 비동기 응답을 기다리는 시그널/슬롯 설계 필요
        """

        if self.use_openapi and self.openapi.available:
            try:
                self.openapi.request_condition_list()
                names = self.openapi.get_condition_list()
                if names:
                    return names
            except Exception as exc:  # pragma: no cover - optional path
                logger.exception("OpenAPI condition list failed: %s", exc)

        # 더미 구현: 실제 API가 붙기 전까지는 하드코딩된 목록을 반환합니다.
        dummy_conditions = ["단기급등_체크", "돌파_추세", "장중급락_반등"]
        return dummy_conditions

    def get_condition_universe(self, condition_name: str) -> List[str]:
        """Return symbols matching the given condition name.

        When OpenAPI is active, this looks up the condition index and sends a
        ``SendCondition`` request before returning the last received universe.
        The demo environment falls back to a static set of tickers.

        TODO: 실사용 시에는 OnReceiveTrCondition 이벤트 완료까지 기다리도록
        비동기 구조를 적용해야 합니다.
        """

        if self.use_openapi and self.openapi.available:
            try:
                condition_index = next((idx for idx, name in self.openapi.conditions if name == condition_name), None)
                if condition_index is not None:
                    self.openapi.request_condition_universe(condition_index, condition_name)
                    universe = self.openapi.get_last_universe()
                    if universe:
                        return universe
            except Exception as exc:  # pragma: no cover - optional path
                logger.exception("OpenAPI condition universe failed: %s", exc)

        # 더미 구현: 조건식 이름과 무관하게 테스트용 종목을 반환합니다.
        return ["005930", "000660", "035420", "068270", "035720"]

    def get_condition_list(self) -> List[str]:
        """Deprecated alias kept for backward compatibility."""

        return self.list_conditions()

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
