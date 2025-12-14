"""Kiwoom OpenAPI+ thin wrapper with safe fallbacks for non-Windows environments.

This module keeps the event-driven QAxWidget-based interface that works on
Windows with Kiwoom OpenAPI+ installed. When PyQt5's QAxContainer is not
available (e.g., Linux CI), the same class name is provided with
``available=False`` so higher-level code can silently fall back to dummy logic.
"""

from __future__ import annotations

import logging
import sys
from typing import List, Tuple

logger = logging.getLogger(__name__)

try:  # pragma: no cover - optional dependency for Windows only
    from PyQt5.QAxContainer import QAxWidget
except ImportError:  # pragma: no cover - not available in Linux CI
    QAxWidget = None  # type: ignore


class KiwoomOpenAPI(QAxWidget if QAxWidget else object):
    """Safe wrapper around KHOpenAPI control.

    In non-Windows environments this class is still importable but sets
    ``available`` to False so callers can avoid raising errors. Real Kiwoom
    logic lives in the methods that perform dynamicCall invocations; these are
    guarded by ``available`` to keep tests green.
    """

    def __init__(self):
        self.available: bool = bool(QAxWidget) and sys.platform.startswith("win")
        self.connected: bool = False
        self.conditions: List[Tuple[int, str]] = []
        self.last_universe: List[str] = []

        if not self.available:
            logger.info("KiwoomOpenAPI unavailable (platform/import) – falling back to dummy mode")
            return

        super().__init__("KHOPENAPI.KHOpenAPICtrl.1")  # type: ignore[misc]
        # Event handlers
        self.OnEventConnect.connect(self._on_event_connect)  # type: ignore[attr-defined]
        self.OnReceiveConditionVer.connect(self._on_receive_condition_ver)  # type: ignore[attr-defined]
        self.OnReceiveTrCondition.connect(self._on_receive_tr_condition)  # type: ignore[attr-defined]

    # -- Connection -----------------------------------------------------
    def connect(self) -> None:
        """Attempt OpenAPI login using CommConnect.

        TODO: 실제 로그인 시에는 UI 스레드에서 호출하고, 이벤트에서 결과를
        처리하는 구조로 재검토해야 합니다.
        """

        if not self.available:
            return
        try:
            self.dynamicCall("CommConnect()")  # type: ignore[attr-defined]
        except Exception as exc:  # pragma: no cover - GUI/runtime dependent
            logger.exception("CommConnect failed: %s", exc)
            self.connected = False

    def is_connected(self) -> bool:
        return self.available and self.connected

    def _on_event_connect(self, err_code: int) -> None:
        logger.info("OpenAPI connect result: %s", err_code)
        self.connected = err_code == 0

    # -- Condition list -------------------------------------------------
    def request_condition_list(self) -> None:
        """Trigger condition list load (0150 조건식).

        TODO: 실사용 시 비동기 응답을 기다렸다가 UI를 갱신해야 합니다.
        """

        if not self.available:
            return
        try:
            self.dynamicCall("GetConditionLoad()")  # type: ignore[attr-defined]
        except Exception as exc:  # pragma: no cover - GUI/runtime dependent
            logger.exception("GetConditionLoad failed: %s", exc)

    def get_condition_list(self) -> List[str]:
        """Return cached condition names.

        If :meth:`request_condition_list` has not been called or nothing was
        received, this returns an empty list to keep callers safe.
        """

        return [name for _, name in self.conditions]

    def _on_receive_condition_ver(self, ret: int, msg: str) -> None:
        logger.info("Condition list received: ret=%s msg=%s", ret, msg)
        if ret != 1:
            self.conditions = []
            return
        try:
            raw_list: str = self.dynamicCall("GetConditionNameList()")  # type: ignore[attr-defined]
        except Exception as exc:  # pragma: no cover - GUI/runtime dependent
            logger.exception("GetConditionNameList failed: %s", exc)
            self.conditions = []
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

    # -- Condition universe ---------------------------------------------
    def request_condition_universe(self, condition_index: int, condition_name: str, market: str = "0") -> None:
        """Request universe for the given condition.

        TODO: 실사용 시에는 OnReceiveTrCondition 이벤트에서 비동기 응답을 기다려야 합니다.
        """

        if not self.available:
            return
        try:
            # The final argument (0) means real-time check disabled
            self.dynamicCall(
                "SendCondition(QString, QString, int, int)",
                "",  # screen number placeholder
                condition_name,
                condition_index,
                int(market),
            )
        except Exception as exc:  # pragma: no cover - GUI/runtime dependent
            logger.exception("SendCondition failed: %s", exc)

    def get_last_universe(self) -> List[str]:
        return list(self.last_universe)

    def _on_receive_tr_condition(self, screen_no: str, code_list: str, condition_name: str, index: int, next_: int) -> None:
        logger.info(
            "ReceiveTrCondition screen=%s condition=%s index=%s next=%s", screen_no, condition_name, index, next_
        )
        # code_list is code1;code2;code3; format
        self.last_universe = [code for code in code_list.split(";") if code]


__all__ = ["KiwoomOpenAPI"]
