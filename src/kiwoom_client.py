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

    def __init__(
        self,
        account_no: str,
        app_key: str = "",
        app_secret: str = "",
        history_store: TradeHistoryStore | None = None,
    ):
        self.account_no = account_no
        self.app_key = app_key
        self.app_secret = app_secret
        self._connected_paper = False
        self._connected_real = False
        self._demo_balance = 1_000_000
        self.openapi: KiwoomOpenAPI | None = None
        self.use_openapi = False
        self._master_name_cache: Dict[str, str] = {}
        self._real_cash: int = 0
        self._real_orderable: int = 0
        self._real_holdings: list = []
        self._last_prices: Dict[str, float] = {}
        self._last_block_reason: str = ""
        self.history_store = history_store

    def attach_openapi(self, openapi: KiwoomOpenAPI) -> None:
        """Attach a GUI-hosted QAx Kiwoom control.

        The QAx control must be created after ``QApplication`` exists, so the GUI
        constructs it and injects it here rather than letting this client create
        it at import time.
        """

        self.openapi = openapi
        # 최신 잔고/보유 현황을 내부에 캐싱해 GUI와 엔진이 동일 데이터를 사용하도록 한다.
        if hasattr(openapi, "balance_received"):
            openapi.balance_received.connect(self._on_balance_signal)  # type: ignore[arg-type]
        if hasattr(openapi, "holdings_received"):
            openapi.holdings_received.connect(self._on_holdings_signal)  # type: ignore[arg-type]
        if hasattr(openapi, "real_data_received"):
            openapi.real_data_received.connect(self._on_real_data)  # type: ignore[arg-type]
        if hasattr(openapi, "chejan_received"):
            openapi.chejan_received.connect(self._on_chejan)  # type: ignore[arg-type]

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

        if self._real_cash:
            return self._real_cash
        try:
            return self._fetch_balance_from_kiwoom_api()
        except Exception as exc:  # pragma: no cover - defensive against API errors
            logger.exception("Failed to fetch real balance: %s", exc)
            return 0

    def _on_balance_signal(self, cash: int, orderable: int) -> None:
        self._real_cash = int(cash)
        self._real_orderable = int(orderable)

    def _on_holdings_signal(self, holdings: list) -> None:
        self._real_holdings = holdings

    def _on_real_data(self, code: str, payload: dict) -> None:
        price = float(payload.get("price", 0) or 0)
        if price:
            self._last_prices[code] = price

    def _on_chejan(self, payload: dict) -> None:
        logger.info("[CHEJAN] payload=%s", payload)
        if not self.history_store:
            return
        raw_fids = payload.get("raw_fids") or {}
        if not isinstance(raw_fids, dict):
            raw_fids = {}

        def get_raw(fid: int) -> str:
            return str(raw_fids.get(str(fid), "")).strip()

        def parse_int(value: str) -> int | None:
            value = str(value).strip().replace(",", "").replace("+", "").replace("-", "")
            if not value:
                return None
            try:
                return int(float(value))
            except Exception:
                return None

        code_raw = get_raw(9001)
        code = code_raw.replace("A", "").strip()
        name = get_raw(302) or None
        order_no = get_raw(9203) or None
        status = get_raw(913) or None
        order_qty = parse_int(get_raw(900))
        order_price = parse_int(get_raw(901))
        side = get_raw(907) or None
        exec_no = get_raw(909) or None
        exec_price = parse_int(get_raw(910))
        exec_qty = parse_int(get_raw(911))
        fee = parse_int(get_raw(938))
        tax = parse_int(get_raw(939))

        if not code:
            return

        event = {
            "mode": "real",
            "event_type": "chejan",
            "gubun": payload.get("gubun"),
            "account": None,
            "code": code,
            "name": name,
            "side": side,
            "order_no": order_no,
            "status": status,
            "order_qty": order_qty,
            "order_price": order_price,
            "exec_no": exec_no,
            "exec_price": exec_price,
            "exec_qty": exec_qty,
            "fee": fee,
            "tax": tax,
            "raw_json": TradeHistoryStore.encode_raw(raw_fids),
        }
        self.history_store.insert_event(event)

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

    def _can_send_real_order(self) -> bool:
        self._last_block_reason = ""
        if not self.openapi:
            self._last_block_reason = "OpenAPI 미초기화로 주문 불가"
            logger.warning("[REAL MODE] %s", self._last_block_reason)
            return False
        if not getattr(self.openapi, "connected", False):
            self._last_block_reason = "OpenAPI 미로그인 상태로 주문 불가"
            logger.warning("[REAL MODE] %s", self._last_block_reason)
            return False
        if hasattr(self.openapi, "is_simulation_server") and self.openapi.is_simulation_server():
            self._last_block_reason = "현재 서버가 모의(raw=1) → 주문 차단"
            logger.warning("[REAL MODE] %s", self._last_block_reason)
            return False
        return True

    def get_last_block_reason(self) -> str:
        return self._last_block_reason

    def list_conditions(self) -> List[str]:
        """Return only condition names for backward compatibility."""

        return [name for _, name in self.get_condition_list()]

    def get_condition_list(self) -> List[Tuple[int, str]]:
        """Return (index, name) tuples for Kiwoom 0150 conditions.

        OpenAPI 사용 가능 시 :class:`KiwoomOpenAPI` 에서 파싱된 조건식을 그대로
        반환하고, 사용 불가 환경에서는 **빈 리스트**를 반환하여 가짜
        조건식으로 매매하지 않도록 합니다.
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

        return []

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

        # 조건검색 결과가 없으면 빈 리스트를 반환해 매매가 발생하지 않도록 한다.
        return []

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

    def send_buy_order(
        self, symbol: str, quantity: int, price: float, hogagb: str = "00", expected_price: float | None = None
    ) -> OrderResult:
        """Send a buy order through OpenAPI.

        ``hogagb`` supports ``"03"`` for market and ``"00"`` for limit. ``price``
        should be 0 for market orders when calling the API, but ``expected_price``
        is kept for reporting and strategy fills.
        """

        display_price = expected_price if expected_price is not None else price
        if self._can_send_real_order():
            ok = False
            if hasattr(self.openapi, "send_order"):
                ok = bool(
                    self.openapi.send_order(
                        rqname="buy",
                        screen_no="9001",
                        accno=self.account_no,
                        order_type=1,
                        code=symbol,
                        qty=int(quantity),
                        price=int(price),
                        hogagb=hogagb,
                        org_order_no="",
                    )
                )
            status = "accepted" if ok else "error"
            logger.info("[REAL MODE] SendOrder buy dispatched=%s hogagb=%s price=%s", ok, hogagb, price)
            return OrderResult(symbol=symbol, quantity=quantity if ok else 0, price=display_price, status=status)
        logger.warning("[REAL MODE] 주문 차단 (server/mock/login 확인 필요)")
        return OrderResult(symbol=symbol, quantity=0, price=display_price, status="blocked")

    def send_sell_order(self, symbol: str, quantity: int, price: float) -> OrderResult:
        if self._can_send_real_order():
            ok = False
            if hasattr(self.openapi, "send_order"):
                ok = bool(
                    self.openapi.send_order(
                        rqname="sell",
                        screen_no="9001",
                        accno=self.account_no,
                        order_type=2,
                        code=symbol,
                        qty=int(quantity),
                        price=int(price),
                        hogagb="00",
                        org_order_no="",
                    )
                )
            status = "accepted" if ok else "error"
            logger.info("[REAL MODE] SendOrder sell dispatched=%s", ok)
            return OrderResult(symbol=symbol, quantity=quantity if ok else 0, price=price, status=status)
        logger.warning("[REAL MODE] 주문 차단 (server/mock/login 확인 필요)")
        return OrderResult(symbol=symbol, quantity=0, price=price, status="blocked")

    def get_current_price(self, symbol: str) -> float:
        """Return a dummy current price for a symbol."""
        if self.openapi:
            cached = getattr(self.openapi, "get_last_price", lambda _c: 0)(symbol)
            if cached:
                return cached
        cached_client = self._last_prices.get(symbol)
        if cached_client:
            return cached_client
        # TODO: 실제 API 연동 시 구현
        base = hash(symbol) % 100_000 / 100 + 10
        return round(base, 2)

    def get_last_price(self, symbol: str) -> float:
        return float(self._last_prices.get(symbol) or 0)

    def get_account_summary(self) -> Dict[str, float]:
        """Return placeholder account summary.

        TODO: 실제 API 연동 시 구현
        """

        return {"cash": 0.0, "equity": 0.0, "pnl": 0.0}

    # -- Master data ---------------------------------------------------
    def get_master_name(self, code: str) -> str:
        """Return the security name for a code, with a small cache."""

        if code in self._master_name_cache:
            return self._master_name_cache[code]

        name = ""
        if self.openapi and self.openapi.connected and sys.platform.startswith("win"):
            self.use_openapi = True
            try:
                ax = getattr(self.openapi, "ax", None)
                if ax and hasattr(ax, "dynamicCall"):
                    name = str(ax.dynamicCall("GetMasterCodeName(QString)", code) or "")
            except Exception as exc:  # pragma: no cover - runtime dependent
                logger.warning("GetMasterCodeName 실패(%s): %s", code, exc)

        if not name:
            # Dummy fallback for environments without live master data
            name = f"UNKNOWN-{code}"

        self._master_name_cache[code] = name
        return name
