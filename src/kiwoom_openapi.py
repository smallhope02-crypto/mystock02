"""Kiwoom OpenAPI+ thin wrapper with safe fallbacks for non-Windows environments.

This module keeps the event-driven QAxWidget-based interface that works on
Windows with Kiwoom OpenAPI+ installed. When PyQt5's QAxContainer is not
available (e.g., Linux CI), the same class name is provided with
``available=False`` so higher-level code can silently fall back to dummy logic.
"""

import importlib.util
import logging
import sys
from typing import List, Tuple

logger = logging.getLogger(__name__)

_PYQT_SPEC = importlib.util.find_spec("PyQt5")
_QAX_SPEC = importlib.util.find_spec("PyQt5.QAxContainer") if _PYQT_SPEC else None
if _QAX_SPEC:
    from PyQt5.QAxContainer import QAxWidget
else:
    QAxWidget = None  # type: ignore[misc]


class KiwoomOpenAPI(QAxWidget if QAxWidget else object):
    """Safe wrapper around KHOpenAPI control with condition search helpers."""

    def __init__(self):
        self.available: bool = bool(QAxWidget) and sys.platform.startswith("win")
        self.is_connected: bool = False
        self.conditions: List[Tuple[int, str]] = []
        self.conditions_loaded: bool = False
        self.last_universe: List[str] = []
        self.screen_no: str = "9000"

        if not self.available:
            logger.info("KiwoomOpenAPI unavailable (platform/import) – falling back to dummy mode")
            return

        try:
            super().__init__("KHOPENAPI.KHOpenAPICtrl.1")  # type: ignore[misc]
        except Exception as exc:  # pragma: no cover - Windows runtime dependent
            logger.exception("Failed to instantiate KHOpenAPI control: %s", exc)
            self.available = False
            return

        try:
            if hasattr(self, "OnEventConnect"):
                self.OnEventConnect.connect(self._on_event_connect)  # type: ignore[attr-defined]
            else:
                raise AttributeError("OnEventConnect not available")
            if hasattr(self, "OnReceiveConditionVer"):
                self.OnReceiveConditionVer.connect(self._on_receive_condition_ver)  # type: ignore[attr-defined]
            else:
                raise AttributeError("OnReceiveConditionVer not available")
            if hasattr(self, "OnReceiveTrCondition"):
                self.OnReceiveTrCondition.connect(self._on_receive_tr_condition)  # type: ignore[attr-defined]
            else:
                raise AttributeError("OnReceiveTrCondition not available")
        except Exception as exc:  # pragma: no cover - Windows runtime dependent
            logger.exception("Failed to bind OpenAPI events: %s", exc)
            self.available = False

    # -- Connection -----------------------------------------------------
    def login(self) -> None:
        """Open the OpenAPI login window and wait for ``OnEventConnect``.

        TODO: 실사용 시에는 UI 스레드에서 호출하고 이벤트 완료까지 대기하는
        비동기/시그널 구조로 보완해야 합니다.
        """

        if not self.available:
            return
        try:
            self.dynamicCall("CommConnect()")  # type: ignore[attr-defined]
        except Exception as exc:  # pragma: no cover - GUI/runtime dependent
            logger.exception("CommConnect failed: %s", exc)
            self.is_connected = False

    def is_openapi_connected(self) -> bool:
        """Return True when OpenAPI login succeeded."""

        return self.available and self.is_connected

    def _on_event_connect(self, err_code: int) -> None:
        logger.info("OpenAPI connect result: %s", err_code)
        self.is_connected = err_code == 0

    # -- Condition list -------------------------------------------------
    def load_conditions(self) -> None:
        """Request condition list loading (0150 조건식)."""

        if not self.available or not self.is_connected:
            return
        try:
            self.dynamicCall("GetConditionLoad()")  # type: ignore[attr-defined]
        except Exception as exc:  # pragma: no cover - GUI/runtime dependent
            logger.exception("GetConditionLoad failed: %s", exc)

    def _fetch_condition_list(self) -> None:
        """Parse condition names from the control and cache them."""

        try:
            raw_list: str = self.dynamicCall("GetConditionNameList()")  # type: ignore[attr-defined]
        except Exception as exc:  # pragma: no cover - GUI/runtime dependent
            logger.exception("GetConditionNameList failed: %s", exc)
            self.conditions = []
            self.conditions_loaded = False
            return

        parsed: List[Tuple[int, str]] = []
        for block in raw_list.split(";"):
            if not block:
                continue
            try:
                idx_str, name = block.split("^")
                parsed.append((int(idx_str), name))
            except ValueError:
                logger.warning("Could not parse condition block: %s", block)
        self.conditions = parsed
        self.conditions_loaded = True

    def get_conditions(self) -> List[Tuple[int, str]]:
        """Return parsed condition tuples or an empty list when unavailable."""

        if not self.available or not self.conditions_loaded:
            return []
        return list(self.conditions)

    def _on_receive_condition_ver(self, ret: int, msg: str) -> None:
        logger.info("Condition list received: ret=%s msg=%s", ret, msg)
        if ret != 1:
            self.conditions = []
            self.conditions_loaded = False
            return
        self._fetch_condition_list()

    # -- Condition universe ---------------------------------------------
    def request_condition_universe(self, condition_index: int, condition_name: str, market: str = "0") -> List[str]:
        """Request universe for the given condition and return last received list.

        TODO: 실사용 시에는 OnReceiveTrCondition 이벤트에서 비동기 응답을 기다려야 합니다.
        """

        if not self.available or not self.is_connected or not self.conditions_loaded:
            return []
        try:
            self.dynamicCall(
                "SendCondition(QString, QString, int, int)",
                self.screen_no,
                condition_name,
                int(condition_index),
                int(market),
            )
        except Exception as exc:  # pragma: no cover - GUI/runtime dependent
            logger.exception("SendCondition failed: %s", exc)
            return []
        return self.get_last_universe()

    def get_last_universe(self) -> List[str]:
        return list(self.last_universe)

    def _on_receive_tr_condition(self, screen_no: str, code_list: str, condition_name: str, index: int, next_: int) -> None:
        logger.info(
            "ReceiveTrCondition screen=%s condition=%s index=%s next=%s", screen_no, condition_name, index, next_
        )
        self.last_universe = [code for code in code_list.split(";") if code]


__all__ = ["KiwoomOpenAPI"]
