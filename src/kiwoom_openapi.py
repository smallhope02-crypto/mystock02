"""PyQt5 QAx-based Kiwoom OpenAPI wrapper.

This module wraps the KHOPENAPI ActiveX control inside a ``QAxWidget`` that is
owned by a ``QObject`` wrapper.  All COM events are received on the QAxWidget
and immediately re-emitted as plain PyQt signals so that the GUI can subscribe
without worrying about overloaded COM signatures.  When QAx is unavailable
non-Windows platforms), a disabled stub keeps imports/tests from crashing.
"""

from __future__ import annotations

import logging
import sys
import traceback
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)

try:  # pragma: no cover - platform dependent
    from PyQt5 import QtCore
    from PyQt5.QAxContainer import QAxWidget

    QAX_AVAILABLE = True
    _QAX_IMPORT_ERROR: Optional[Exception] = None
except Exception as exc:  # pragma: no cover - fallback on CI/non-Windows
    QAX_AVAILABLE = False
    _QAX_IMPORT_ERROR = exc
    QtCore = None  # type: ignore


class _DisabledOpenAPI:
    """Fallback implementation used when QAxWidget is unavailable."""

    def __init__(self, *args, **kwargs):
        self.enabled = False
        self.available = False
        self.connected = False
        self.conditions_loaded = False
        self.conditions: List[Tuple[str, str]] = []
        self.last_universe: List[str] = []
        self.screen_no = "9000"
        self.init_error = _QAX_IMPORT_ERROR
        self._init_error = _QAX_IMPORT_ERROR
        self._control = None
        self.ax = None
        if _QAX_IMPORT_ERROR:
            print(f"[OpenAPI] QAx unavailable: {_QAX_IMPORT_ERROR}")

    # Compatibility helpers --------------------------------------------
    def debug_status(self) -> str:
        return (
            f"enabled={self.enabled}, available={self.available}, control={'OK' if self.ax else 'None'}, "
            f"connected={self.connected}, conditions_loaded={self.conditions_loaded}, init_error={repr(self.init_error)}"
        )

    def is_enabled(self) -> bool:
        return False

    def initialize_control(self) -> None:
        """No-op for disabled environments."""

    def _safe_comm_connect(self, context: str = "") -> bool:
        return False

    def login(self) -> bool:
        return False

    def connect_for_conditions(self) -> bool:
        return False

    def comm_connect(self) -> bool:
        return False

    def load_conditions(self) -> None:
        pass

    def fetch_condition_list(self) -> None:
        self.conditions = []
        self.conditions_loaded = False

    def get_conditions(self) -> List[Tuple[str, str]]:
        return []

    def request_condition_universe(self, condition_index: int, condition_name: str, market: str = "0") -> List[str]:
        return []

    def get_condition_name_list(self) -> List[Tuple[int, str]]:
        return []

    def send_condition(self, screen_no: str, condition_name: str, index: int, search_type: int) -> None:
        return None

    def get_last_universe(self) -> List[str]:
        return []


if not QAX_AVAILABLE:  # pragma: no cover - fallback path
    KiwoomOpenAPI = _DisabledOpenAPI  # type: ignore
else:

    class KiwoomOpenAPI(QtCore.QObject):  # pragma: no cover - GUI/runtime heavy
        """QObject wrapper that hosts KHOPENAPI inside a hidden QAxWidget.

        ``login_result`` is a single-signature ``pyqtSignal(int)`` that mirrors
        the OpenAPI ``OnEventConnect`` callback to avoid the overloaded COM
        signal signatures that previously caused connection errors in the GUI.
        """

        login_result = QtCore.pyqtSignal(int)
        condition_ver_received = QtCore.pyqtSignal(int, str)
        tr_condition_received = QtCore.pyqtSignal(str, str, str, int, str)
        real_condition_received = QtCore.pyqtSignal(str, str, str, str)

        def __init__(self, parent=None):
            super().__init__(parent)
            self.enabled = False
            self.available = False
            self.connected = False
            self.conditions_loaded = False
            self.conditions: List[Tuple[str, str]] = []
            self.last_universe: List[str] = []
            self.screen_no = "9000"
            self.init_error: Optional[Exception] = None
            self._init_error: Optional[Exception] = None
            self._control: Optional[object] = None
            self.ax: Optional[QAxWidget] = None
            self._wire_control()

        # -- Setup ------------------------------------------------------
        def _wire_control(self) -> None:
            print("[OpenAPI] initialize_control invoked", flush=True)
            print(
                f"[OpenAPI] runtime Python={sys.version.split()[0]} PyQt5={QtCore.PYQT_VERSION_STR}",
                flush=True,
            )
            if not sys.platform.startswith("win"):
                self.init_error = RuntimeError("Windows 환경에서만 지원됩니다")
                print("[OpenAPI] Non-Windows platform; QAx disabled")
                return
            try:
                self.ax = QAxWidget(parent=self)
                self.ax.setControl("KHOPENAPI.KHOpenAPICtrl.1")
                self._control = self.ax  # legacy compatibility for tests/clients
                self.enabled = True
                self.available = True
                self.init_error = None
                self._init_error = None
                print("[OpenAPI] KHOpenAPI control created via QAxWidget")
            except Exception as exc:  # pragma: no cover - runtime dependent
                self.enabled = False
                self.available = False
                self.init_error = exc
                self._init_error = exc
                self.ax = None
                print("[OpenAPI] QAx control creation failed:", repr(exc))
                traceback.print_exc()
                return

            self._bind_signals()

        def _bind_signals(self) -> None:
            """Connect Kiwoom ActiveX events to Python handlers."""

            if not self.ax:
                return

            bindings = {
                "OnEventConnect": self._on_event_connect,
                "OnReceiveConditionVer": self._on_receive_condition_ver,
                "OnReceiveTrCondition": self._on_receive_tr_condition,
                "OnReceiveRealCondition": self._on_receive_real_condition,
            }

            for name, handler in bindings.items():
                try:
                    event_obj = getattr(self.ax, name, None)
                    if event_obj and hasattr(event_obj, "connect"):
                        event_obj.connect(handler)
                        print(f"[OpenAPI] bound {name} via direct attribute")
                    else:
                        raise AttributeError(f"{name} signal not found")
                except Exception as exc:  # pragma: no cover - runtime dependent
                    print(f"[OpenAPI] Failed to bind {name}: {exc!r}")
                    traceback.print_exc()

        def initialize_control(self) -> None:
            """Re-run control setup if it was previously disabled."""

            if self.enabled and self.available and self.ax:
                return
            self._wire_control()

        def debug_status(self) -> str:
            return (
                f"enabled={self.enabled}, available={self.available}, control={'OK' if self.ax else 'None'}, "
                f"connected={self.connected}, conditions_loaded={self.conditions_loaded}, init_error={repr(self.init_error)}"
            )

        def is_enabled(self) -> bool:
            return bool(self.enabled and self.ax is not None)

        # -- Connection --------------------------------------------------
        def _safe_comm_connect(self, context: str = "") -> bool:
            status_before = self.debug_status()
            print(f"[OpenAPI] Calling CommConnect() context={context}, status(before)={status_before}")

            if not self.is_enabled():
                msg = "[OpenAPI] CommConnect 호출 불가: 컨트롤이 활성 상태가 아님."
                print(msg)
                self.init_error = RuntimeError(msg)
                self._init_error = self.init_error
                return False

            target = self._control or self.ax
            try:
                if target and hasattr(target, "dynamicCall"):
                    target.dynamicCall("CommConnect()")
                else:
                    raise RuntimeError("CommConnect 호출 수단이 없습니다")
                self.init_error = None
                self._init_error = None
                print(f"[OpenAPI] CommConnect() 호출 완료 (context={context})")
                return True
            except Exception as exc:  # pragma: no cover - runtime dependent
                self.init_error = exc
                self._init_error = exc
                print(f"[OpenAPI] CommConnect 예외 발생 in {context}: {repr(exc)}")
                traceback.print_exc()
                return False

        def login(self) -> bool:
            return self._safe_comm_connect(context="login")

        def connect_for_conditions(self) -> bool:
            return self._safe_comm_connect(context="condition-login")

        def comm_connect(self) -> bool:
            return self._safe_comm_connect(context="manual")

        def is_openapi_connected(self) -> bool:
            return bool(self.connected)

        # -- Condition list ---------------------------------------------
        def load_conditions(self) -> None:
            if not (self.is_enabled() and self.connected):
                print("[OpenAPI] 로그인 후 조건 로딩을 시도하세요")
                return
            try:
                target = self.ax
                if target and hasattr(target, "dynamicCall"):
                    target.dynamicCall("GetConditionLoad()")
                else:
                    raise RuntimeError("GetConditionLoad 사용 불가")
                print("[OpenAPI] 조건식 로딩 요청")
            except Exception as exc:
                print(f"[OpenAPI] GetConditionLoad 실패: {exc}")
                traceback.print_exc()
                self.init_error = exc

        def fetch_condition_list(self) -> None:
            if not (self.is_enabled() and self.connected):
                self.conditions = []
                self.conditions_loaded = False
                return
            try:
                target = self.ax
                if target and hasattr(target, "dynamicCall"):
                    raw_list = target.dynamicCall("GetConditionNameList()")
                else:
                    raise RuntimeError("GetConditionNameList 사용 불가")
            except Exception as exc:  # pragma: no cover - runtime dependent
                print(f"[OpenAPI] GetConditionNameList 실패: {exc}")
                traceback.print_exc()
                self.conditions = []
                self.conditions_loaded = False
                self.init_error = exc
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
            print(f"[OpenAPI] 조건식 {len(self.conditions)}개 로딩 완료")

        def get_conditions(self) -> List[Tuple[str, str]]:
            if not self.conditions_loaded:
                return []
            return list(self.conditions)

        def get_condition_name_list(self) -> List[Tuple[int, str]]:
            return [(int(idx), name) for idx, name in self.get_conditions()]

        # -- Condition universe -----------------------------------------
        def send_condition(self, screen_no: str, condition_name: str, index: int, search_type: int = 1) -> None:
            """Run a condition by index/name and optionally register real-time (search_type=1)."""

            if not self.conditions_loaded:
                print("[OpenAPI] 조건식이 로딩되지 않았습니다.")
                return
            target = self.ax
            try:
                if target and hasattr(target, "dynamicCall"):
                    target.dynamicCall(
                        "SendCondition(QString, QString, int, int)", screen_no, condition_name, int(index), int(search_type)
                    )
                else:
                    raise RuntimeError("SendCondition 사용 불가")
            except Exception as exc:
                print(f"[OpenAPI] SendCondition 실패: {exc}")
                traceback.print_exc()

        def request_condition_universe(self, condition_index: int, condition_name: str, search_type: int = 0) -> List[str]:
            if not self.conditions_loaded:
                print("[OpenAPI] 조건식 조회 불가 (조건 로딩 필요)")
                return []
            self.send_condition(self.screen_no, condition_name, condition_index, int(search_type))
            return self.get_last_universe()

        def get_last_universe(self) -> List[str]:
            return list(self.last_universe)

        # -- Event handlers ---------------------------------------------
        def _on_event_connect(self, err_code: int) -> None:
            """Handle Kiwoom OnEventConnect and relay as a single int signal."""

            try:
                ec = int(err_code)
            except Exception:
                ec = -1
            self.connected = ec == 0
            print(f"[OpenAPI] OnEventConnect err_code={ec} enabled={self.enabled}")
            self.login_result.emit(ec)
            if self.connected:
                self.load_conditions()

        def _on_receive_condition_ver(self, lRet: int, sMsg: str) -> None:
            print(f"[OpenAPI] OnReceiveConditionVer ret={lRet} msg={sMsg}")
            if lRet == 1:
                self.fetch_condition_list()
            self.condition_ver_received.emit(int(lRet), str(sMsg))

        def _on_receive_tr_condition(self, screen_no: str, code_list: str, condition_name: str, index: int, next_: str) -> None:
            print(
                f"[OpenAPI] OnReceiveTrCondition screen={screen_no} condition={condition_name} index={index} next={next_} codes={code_list}"
            )
            self.last_universe = [code for code in str(code_list).split(";") if code]
            self.tr_condition_received.emit(str(screen_no), str(code_list), str(condition_name), int(index), str(next_))

        def _on_receive_real_condition(self, code: str, event: str, condition_name: str, condition_index: str) -> None:
            print(
                f"[OpenAPI] OnReceiveRealCondition code={code} event={event} condition={condition_name} index={condition_index}"
            )
            self.real_condition_received.emit(str(code), str(event), str(condition_name), str(condition_index))


__all__ = ["KiwoomOpenAPI", "QAX_AVAILABLE"]
