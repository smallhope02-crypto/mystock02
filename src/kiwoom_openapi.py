"""Kiwoom OpenAPI+ wrapper with COM events and safe fallbacks.

This module uses ``win32com.client.DispatchWithEvents`` to subscribe to
``OnEventConnect``, ``OnReceiveConditionVer``, and ``OnReceiveTrCondition``
events. When the KHOpenAPI control cannot be created (non-Windows or missing
OpenAPI install), the wrapper stays disabled so higher-level code can fall back
without crashing.
"""

import logging
import sys
from typing import List, Optional, Tuple

try:  # pragma: no cover - platform specific
    from win32com.client import DispatchWithEvents
except ImportError:  # pragma: no cover - expected on non-Windows
    DispatchWithEvents = None  # type: ignore[misc]

logger = logging.getLogger(__name__)


class _KiwoomEventHandler:
    """Event sink passed to ``DispatchWithEvents``.

    The outer :class:`KiwoomOpenAPI` instance is injected so we can mutate
    connection state and trigger follow-up requests.
    """

    def __init__(self, outer: "KiwoomOpenAPI"):
        self.outer = outer

    def OnEventConnect(self, err_code):  # pragma: no cover - runtime callback
        self.outer.connected = err_code == 0
        if self.outer.connected:
            self.outer.available = True
            logger.info("[OpenAPI] 로그인 성공 (err_code=%s)", err_code)
            # 로그인 성공 시 바로 조건식 로딩을 시작한다.
            self.outer.load_conditions()
        else:
            self.outer.conditions_loaded = False
            logger.warning("[OpenAPI] 로그인 실패 (err_code=%s)", err_code)

    def OnReceiveConditionVer(self, lRet, sMsg):  # pragma: no cover - runtime callback
        logger.info("[OpenAPI] 조건식 버전 수신: ret=%s msg=%s", lRet, sMsg)
        if lRet == 1:
            self.outer.fetch_condition_list()
            logger.info("[OpenAPI] 조건식 %d개 로딩 완료", len(self.outer.conditions))
        else:
            self.outer.conditions_loaded = False
            logger.warning("[OpenAPI] 조건식 버전 수신 실패")

    def OnReceiveTrCondition(self, screen_no, code_list, condition_name, index, next_):  # pragma: no cover - runtime callback
        logger.info(
            "[OpenAPI] 조건식 종목 수신 screen=%s condition=%s index=%s next=%s",
            screen_no,
            condition_name,
            index,
            next_,
        )
        self.outer.last_universe = [code for code in str(code_list).split(";") if code]


class KiwoomOpenAPI:
    """Safe wrapper around KHOpenAPI control with condition search helpers."""

    def __init__(self):
        self.available: bool = False
        self.connected: bool = False
        self.conditions_loaded: bool = False
        self.conditions: List[Tuple[str, str]] = []
        self.last_universe: List[str] = []
        self.screen_no: str = "9000"
        self._control: Optional[object] = None

        if not (DispatchWithEvents and sys.platform.startswith("win")):
            logger.info("[OpenAPI] win32com unavailable or non-Windows platform; disabling")
            return

    # -- Control setup ---------------------------------------------------
    def initialize_control(self) -> None:
        """Create the KHOpenAPI control and bind events.

        Control creation errors leave ``available=False`` so callers can fall
        back without raising.
        """

        if self._control is not None or not (DispatchWithEvents and sys.platform.startswith("win")):
            return
        try:
            self._control = DispatchWithEvents(
                "KHOPENAPI.KHOpenAPICtrl.1", lambda: _KiwoomEventHandler(self)
            )
            self.available = True
            logger.info("[OpenAPI] KHOpenAPI 컨트롤 생성 완료")
        except Exception as exc:  # pragma: no cover - Windows runtime dependent
            logger.exception("[OpenAPI] 컨트롤 생성 실패: %s", exc)
            self.available = False
            self._control = None

    # -- Connection -----------------------------------------------------
    def login(self) -> None:
        """Show the OpenAPI login dialog (CommConnect)."""

        if not self.available:
            logger.warning("[OpenAPI] 컨트롤이 비활성 상태입니다. 로그인 불가")
            return
        try:
            self._control.CommConnect()
            logger.info("[OpenAPI] 로그인 시도")
        except Exception as exc:  # pragma: no cover - runtime dependent
            logger.exception("[OpenAPI] CommConnect 호출 실패: %s", exc)
            self.connected = False

    def is_openapi_connected(self) -> bool:
        """Return True when OpenAPI login succeeded."""

        return self.available and self.connected

    # -- Condition list -------------------------------------------------
    def load_conditions(self) -> None:
        """Request condition list loading (0150 조건식)."""

        if not (self.available and self.connected and self._control):
            logger.warning("[OpenAPI] 로그인 후 조건 로딩을 시도하세요")
            return
        try:
            self._control.GetConditionLoad()
            logger.info("[OpenAPI] 조건식 로딩 요청")
        except Exception as exc:  # pragma: no cover - GUI/runtime dependent
            logger.exception("[OpenAPI] GetConditionLoad 실패: %s", exc)

    def fetch_condition_list(self) -> None:
        """Parse condition names from the control and cache them."""

        if not (self.available and self.connected and self._control):
            return
        try:
            raw_list = self._control.GetConditionNameList()
        except Exception as exc:  # pragma: no cover - GUI/runtime dependent
            logger.exception("[OpenAPI] GetConditionNameList 실패: %s", exc)
            self.conditions = []
            self.conditions_loaded = False
            return

        parsed: List[Tuple[str, str]] = []
        for block in str(raw_list).split(";"):
            if not block:
                continue
            try:
                idx_str, name = block.split("^")
                parsed.append((idx_str, name))
            except ValueError:
                logger.warning("[OpenAPI] 조건식 파싱 실패: %s", block)
        self.conditions = parsed
        self.conditions_loaded = True

    def get_conditions(self) -> List[Tuple[str, str]]:
        """Return parsed condition tuples or an empty list when unavailable."""

        if not self.available or not self.conditions_loaded:
            return []
        return list(self.conditions)

    # -- Condition universe ---------------------------------------------
    def request_condition_universe(self, condition_index: int, condition_name: str, market: str = "0") -> List[str]:
        """Request universe for the given condition and return last received list.

        TODO: 실사용 시에는 OnReceiveTrCondition 이벤트에서 비동기 응답을 기다려야 합니다.
        """

        if not (self.available and self.connected and self.conditions_loaded and self._control):
            logger.warning("[OpenAPI] 조건식 조회 불가 (로그인/로딩 상태 확인)")
            return []
        try:
            self._control.SendCondition(self.screen_no, condition_name, int(condition_index), int(market))
        except Exception as exc:  # pragma: no cover - GUI/runtime dependent
            logger.exception("[OpenAPI] SendCondition 실패: %s", exc)
            return []
        return self.get_last_universe()

    def get_last_universe(self) -> List[str]:
        return list(self.last_universe)


__all__ = ["KiwoomOpenAPI"]
