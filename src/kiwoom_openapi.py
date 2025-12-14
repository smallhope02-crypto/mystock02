"""Kiwoom OpenAPI+ wrapper with COM events and safe fallbacks.

This module uses ``win32com.client.DispatchWithEvents`` to subscribe to
``OnEventConnect``, ``OnReceiveConditionVer``, and ``OnReceiveTrCondition``
events. When the KHOpenAPI control cannot be created (non-Windows or missing
OpenAPI install), the wrapper stays disabled so higher-level code can fall back
without crashing.
"""

import logging
import sys
import traceback
from typing import List, Optional, Tuple

try:  # pragma: no cover - platform dependent
    import pywintypes
except Exception:  # pragma: no cover - fallback when pywin32 is absent
    pywintypes = None

try:  # pragma: no cover - platform specific
    from win32com.client import Dispatch, DispatchWithEvents, WithEvents
    _DISPATCH_IMPORT_ERROR: Optional[ImportError] = None
except ImportError as import_error:  # pragma: no cover - expected on non-Windows
    Dispatch = None  # type: ignore[misc]
    DispatchWithEvents = None  # type: ignore[misc]
    WithEvents = None  # type: ignore[misc]
    _DISPATCH_IMPORT_ERROR = import_error

logger = logging.getLogger(__name__)


class KiwoomEventHandler:
    """Pure-Python COM event sink used by ``DispatchWithEvents``.

    **Important**: Do **not** inherit from QObject/PyQt types. ``DispatchWithEvents``
    dynamically builds a multiple-inheritance class with the COM event base and the
    provided handler class; using QObject (``sip.wrappertype``) would trigger the
    metaclass conflict seen on 32-bit Windows. The owner (``KiwoomOpenAPI``) is
    attached after creation via ``handler._owner = <KiwoomOpenAPI>``.
    """

    def __init__(self):
        # ``DispatchWithEvents`` expects a zero-arg initializer. Owner is injected
        # after creation to avoid metaclass conflicts with PyQt/QObject.
        self._owner: Optional["KiwoomOpenAPI"] = None

    def set_owner(self, owner: "KiwoomOpenAPI") -> None:
        """Attach the outer wrapper after COM object creation."""

        self._owner = owner

    def OnEventConnect(self, err_code):  # pragma: no cover - runtime callback
        if self._owner:
            self._owner._on_event_connect(err_code)

    def OnReceiveConditionVer(self, lRet, sMsg):  # pragma: no cover - runtime callback
        if self._owner:
            self._owner._on_receive_condition_ver(lRet, sMsg)

    def OnReceiveTrCondition(self, screen_no, code_list, condition_name, index, next_):  # pragma: no cover - runtime callback
        if self._owner:
            self._owner._on_receive_tr_condition(screen_no, code_list, condition_name, index, next_)


class KiwoomOpenAPI:
    """Safe wrapper around KHOpenAPI control with condition search helpers."""

    def __init__(self):
        self.available: bool = False
        self._enabled: bool = False
        self.connected: bool = False
        self.conditions_loaded: bool = False
        self.conditions: List[Tuple[str, str]] = []
        self.last_universe: List[str] = []
        self.screen_no: str = "9000"
        self._control: Optional[object] = None
        self._init_error: Optional[Exception] = None

        # Control creation is deferred to ``initialize_control`` so GUI code can
        # retry on demand. We keep the state fields initialized here.

    # -- Control setup ---------------------------------------------------
    def initialize_control(self) -> None:
        """Create the KHOpenAPI control and bind events.

        Control creation errors leave ``available=False`` so callers can fall
        back without raising.
        """

        print("[OpenAPI] initialize_control invoked", flush=True)
        if self._control is not None:
            print("[OpenAPI] Control already initialized; skipping")
            return

        if not sys.platform.startswith("win"):
            self._init_error = RuntimeError("Windows 환경에서만 지원됩니다")
            self._enabled = False
            self.available = False
            logger.info("[OpenAPI] Non-Windows platform detected; disabling")
            return
        if Dispatch is None:
            # Preserve the original ImportError so users can diagnose missing
            # win32com installations instead of seeing a wrapped RuntimeError.
            self._init_error = _DISPATCH_IMPORT_ERROR
            self._enabled = False
            self.available = False
            print("[OpenAPI] win32com Dispatch import 실패:", repr(_DISPATCH_IMPORT_ERROR), flush=True)
            return

        # 1단계: 기본 COM 컨트롤 생성
        try:
            print("[OpenAPI] trying Dispatch KHOPENAPI.KHOpenAPICtrl.1", flush=True)
            base = Dispatch("KHOPENAPI.KHOpenAPICtrl.1")
            print("[OpenAPI] Dispatch OK:", type(base), flush=True)
        except Exception as exc:  # pragma: no cover - Windows runtime dependent
            self._control = None
            self._enabled = False
            self.available = False
            self._init_error = exc
            print("[OpenAPI] Dispatch error(raw):", repr(exc))
            traceback.print_exc()
            logger.exception("[OpenAPI] KHOPENAPI Dispatch 실패: %s", exc)
            return

        # 2단계: 이벤트 바인딩 시도
        control = None
        event_error: Optional[Exception] = None
        try:
            print("[OpenAPI] DispatchWithEvents 시도", flush=True)
            control = DispatchWithEvents(base, KiwoomEventHandler)
        except Exception as exc:  # pragma: no cover - Windows runtime dependent
            event_error = exc
            print("[OpenAPI] DispatchWithEvents 실패, WithEvents 폴백 시도:", repr(exc))
            traceback.print_exc()
            try:
                control = WithEvents(base, KiwoomEventHandler) if WithEvents else None
            except Exception as exc2:  # pragma: no cover - Windows runtime dependent
                event_error = exc2
                print("[OpenAPI] WithEvents 폴백도 실패:", repr(exc2))
                traceback.print_exc()

        if control is None:
            self._control = None
            self._enabled = False
            self.available = False
            self._init_error = event_error or RuntimeError("이벤트 바인딩 실패")
            print("[OpenAPI] 이벤트 바인딩 실패로 비활성화됨")
            return

        # 3단계: 이벤트 핸들러에 owner 연결
        try:
            handler = getattr(control, "_eventobj_", None)
            if isinstance(handler, KiwoomEventHandler):
                handler._owner = self
            elif isinstance(control, KiwoomEventHandler):
                control._owner = self
            elif hasattr(control, "set_owner"):
                control.set_owner(self)  # type: ignore[attr-defined]
        except Exception:
            logger.warning("[OpenAPI] 이벤트 핸들러에 owner 연결 실패")

        # 4단계: 성공 상태 업데이트
        self._control = control
        self.available = True
        self._enabled = True
        self._init_error = None
        print("[OpenAPI] KHOpenAPI control created and events bound successfully.")
        logger.info("[OpenAPI] KHOpenAPI 컨트롤 생성 완료")

    def debug_status(self) -> str:
        """Return a human-readable status string for debugging."""

        return (
            f"enabled={self._enabled}, available={self.available}, control={'OK' if self._control is not None else 'None'}, "
            f"connected={self.connected}, conditions_loaded={self.conditions_loaded}, "
            f"init_error={repr(self._init_error)}"
        )

    def is_enabled(self) -> bool:
        """Return True when the COM control was created successfully."""

        return bool(self._enabled and self._control is not None)

    # -- Connection -----------------------------------------------------
    def _safe_comm_connect(self, context: str = "") -> bool:
        """Centralized CommConnect guard that never raises to callers."""

        status_before = self.debug_status()
        print(f"[OpenAPI] Calling CommConnect() context={context}, status(before)={status_before}")

        if not self.available or not self.is_enabled() or self._control is None:
            msg = "[OpenAPI] CommConnect 호출 불가: 컨트롤이 활성 상태가 아님."
            print(msg)
            self._init_error = RuntimeError(msg)
            return False
        try:
            self._control.CommConnect()
            self._init_error = None
            print(f"[OpenAPI] CommConnect() 호출 완료 (context={context}, 이벤트 대기)")
            return True
        except Exception as exc:  # pragma: no cover - runtime dependent
            # Preserve pywintypes.com_error or other exceptions for diagnostics
            self._init_error = exc
            self.connected = False
            if pywintypes and isinstance(exc, pywintypes.com_error):
                print(f"[OpenAPI] CommConnect pywintypes.com_error in {context}: {repr(exc)}")
            else:
                print(f"[OpenAPI] CommConnect 예외 발생 in {context}: {repr(exc)}")
            logger.exception("[OpenAPI] CommConnect 호출 실패: %s", exc)
            return False

    def login(self) -> bool:
        """Show the OpenAPI login dialog (CommConnect) with guarded errors."""

        return self._safe_comm_connect(context="login")

    def connect_for_conditions(self) -> bool:
        """Explicit helper for condition login path used by the GUI."""

        if not self.is_enabled():
            print("[OpenAPI] connect_for_conditions called but control is disabled")
            print(f"[OpenAPI] debug_status: {self.debug_status()}")
            logger.warning("[OpenAPI] connect_for_conditions: control disabled; reinitializing")
            self.initialize_control()
            print("[OpenAPI] debug_status after reinit:", self.debug_status())
            if not self.is_enabled():
                return False
        return self._safe_comm_connect(context="condition-login")

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

    # -- Event handlers (called from COM sink) --------------------------
    def _on_event_connect(self, err_code: int) -> None:
        self.connected = err_code == 0
        self.available = self.available and self._enabled
        print(f"[OpenAPI] OnEventConnect err_code={err_code} enabled={self._enabled}")
        if self.connected:
            logger.info("[OpenAPI] 로그인 성공 (err_code=%s)", err_code)
            self.load_conditions()
        else:
            self.conditions_loaded = False
            logger.warning("[OpenAPI] 로그인 실패 (err_code=%s)", err_code)

    def _on_receive_condition_ver(self, lRet: int, sMsg: str) -> None:
        logger.info("[OpenAPI] 조건식 버전 수신: ret=%s msg=%s", lRet, sMsg)
        print(f"[OpenAPI] OnReceiveConditionVer ret={lRet} msg={sMsg}")
        if lRet == 1:
            self.fetch_condition_list()
            logger.info("[OpenAPI] 조건식 %d개 로딩 완료", len(self.conditions))
            print(f"[OpenAPI] 조건식 {len(self.conditions)}개 로딩 완료")
        else:
            self.conditions_loaded = False
            logger.warning("[OpenAPI] 조건식 버전 수신 실패")

    def _on_receive_tr_condition(
        self, screen_no: str, code_list: str, condition_name: str, index: int, next_: str
    ) -> None:
        logger.info(
            "[OpenAPI] 조건식 종목 수신 screen=%s condition=%s index=%s next=%s",
            screen_no,
            condition_name,
            index,
            next_,
        )
        print(
            f"[OpenAPI] OnReceiveTrCondition screen={screen_no} condition={condition_name} index={index} next={next_} codes={code_list}"
        )
        self.last_universe = [code for code in str(code_list).split(";") if code]


__all__ = ["KiwoomOpenAPI"]
