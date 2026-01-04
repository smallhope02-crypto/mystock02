"""PyQt5 QAx-based Kiwoom OpenAPI wrapper.

This module wraps the KHOPENAPI ActiveX control inside a ``QAxWidget`` that is
owned by a ``QObject`` wrapper.  All COM events are received on the QAxWidget
and immediately re-emitted as plain PyQt signals so that the GUI can subscribe
without worrying about overloaded COM signatures.  When QAx is unavailable
non-Windows platforms), a disabled stub keeps imports/tests from crashing.
"""

from __future__ import annotations

import logging
import os
import sys
import traceback
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)

try:  # pragma: no cover - platform dependent
    from PyQt5 import QtCore, QtWidgets
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
        self.last_prices: dict[str, float] = {}
        self.real_data_received = None
        self._pw_window_shown: bool = False
        if _QAX_IMPORT_ERROR:
            print(f"[OpenAPI] QAx unavailable: {_QAX_IMPORT_ERROR}")
        self.accounts = []

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

    def allocate_screen_no(self, key: int) -> str:
        base = 5000
        offset = key % 800  # keep within 4 digits and avoid 0000
        screen = base + offset
        if screen % 10000 == 0:
            screen += 1
        return f"{screen:04d}"

    def send_condition(self, screen_no: str, condition_name: str, index: int, search_type: int) -> int:
        print(
            f"[OpenAPI-disabled] SendCondition screen={screen_no} name={condition_name} index={index} search_type={search_type}"
        )
        return 0

    def get_last_universe(self) -> List[str]:
        return []

    def request_account_list(self) -> None:
        return None

    def request_balance(self, account_no: str, rqname: str = "opw00001-balance") -> None:
        return None

    def request_deposit_and_holdings(self, account_no: str, account_pw: str | None = None) -> bool:
        print("[OpenAPI-disabled] 잔고 조회는 QAx 환경에서만 지원됩니다")
        return False

    def show_account_password_window(self) -> bool:
        print("[OpenAPI-disabled] ShowAccountWindow는 QAx 환경에서만 지원됩니다")
        return False

    def get_server_gubun(self) -> str:
        return ""

    def get_server_gubun_raw(self) -> str:
        return ""

    def set_real_reg(self, codes: List[str], fids: str = "10;11;12", screen_no: str = "9999") -> None:
        return None

    def get_last_price(self, code: str) -> float:
        return float(self.last_prices.get(code, 0))

    def send_order(
        self,
        rqname: str,
        screen_no: str,
        accno: str,
        order_type: int,
        code: str,
        qty: int,
        price: int,
        hogagb: str,
        org_order_no: str = "",
    ) -> bool:
        print("[OpenAPI] SendOrder skipped: QAx unavailable")
        return False


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
        real_data_received = QtCore.pyqtSignal(str, dict)
        chejan_received = QtCore.pyqtSignal(dict)
        accounts_received = QtCore.pyqtSignal(list)
        balance_received = QtCore.pyqtSignal(int, int)  # (cash, orderable)
        holdings_received = QtCore.pyqtSignal(list)  # list of dicts
        server_gubun_changed = QtCore.pyqtSignal(str)

        def __init__(self, parent=None, qwidget_parent: Optional[QtWidgets.QWidget] = None):
            super().__init__(parent)
            self._widget_parent: Optional[QtWidgets.QWidget] = (
                qwidget_parent if isinstance(qwidget_parent, QtWidgets.QWidget) else None
            )
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
            self._condition_load_requested: bool = False
            self.accounts: List[str] = []
            self.server_gubun: str = ""
            self.last_prices: dict[str, float] = {}
            self._pw_window_shown: bool = False
            self._wire_control()

        # -- Setup ------------------------------------------------------
        def _wire_control(self) -> None:
            print("[OpenAPI] initialize_control invoked", flush=True)
            print(f"[OpenAPI] module_path={__file__}", flush=True)
            print(f"[OpenAPI] cwd={os.getcwd()}", flush=True)
            print(
                f"[OpenAPI] runtime Python={sys.version.split()[0]} PyQt5={QtCore.PYQT_VERSION_STR} exe={sys.executable}",
                flush=True,
            )
            if not sys.platform.startswith("win"):
                self.init_error = RuntimeError("Windows 환경에서만 지원됩니다")
                print("[OpenAPI] Non-Windows platform; QAx disabled")
                return
            try:
                if self._widget_parent:
                    self.ax = QAxWidget("KHOPENAPI.KHOpenAPICtrl.1", parent=self._widget_parent)
                else:
                    self.ax = QAxWidget("KHOPENAPI.KHOpenAPICtrl.1")
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
                "OnReceiveTrData": self._on_receive_tr_data,
                "OnReceiveRealData": self._on_receive_real_data,
                "OnReceiveChejanData": self._on_receive_chejan_data,
                "OnReceiveMsg": self._on_receive_msg,
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
                f"connected={self.connected}, conditions_loaded={self.conditions_loaded}, "
                f"init_error={repr(self.init_error)}, server_gubun={self.server_gubun!r}"
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
            if self._condition_load_requested:
                print("[OpenAPI] skip GetConditionLoad: already requested")
                return
            try:
                target = self.ax
                if target and hasattr(target, "dynamicCall"):
                    import traceback

                    print(f"[OpenAPI] self_id={id(self)} GetConditionLoad caller:\n" + "".join(traceback.format_stack(limit=12)))
                    target.dynamicCall("GetConditionLoad()")
                else:
                    raise RuntimeError("GetConditionLoad 사용 불가")
                self._condition_load_requested = True
                print("[OpenAPI] 조건식 로딩 요청")
            except Exception as exc:
                print(f"[OpenAPI] GetConditionLoad 실패: {exc}")
                traceback.print_exc()
                self.init_error = exc

        def fetch_condition_list(self, apply: bool = True) -> List[Tuple[str, str]]:
            if not (self.is_enabled() and self.connected):
                if apply:
                    self.conditions = []
                    self.conditions_loaded = False
                return []
            try:
                target = self.ax
                if target and hasattr(target, "dynamicCall"):
                    raw_list = target.dynamicCall("GetConditionNameList()")
                else:
                    raise RuntimeError("GetConditionNameList 사용 불가")
            except Exception as exc:  # pragma: no cover - runtime dependent
                print(f"[OpenAPI] GetConditionNameList 실패: {exc}")
                traceback.print_exc()
                if apply:
                    self.conditions = []
                    self.conditions_loaded = False
                    self.init_error = exc
                return []

            raw_str = str(raw_list or "")
            head = raw_str[:200]
            tail = raw_str[-200:] if len(raw_str) > 200 else ""
            print(
                f"[OpenAPI] GetConditionNameList raw_len={len(raw_str)} head='{head}' tail='{tail}'"
            )

            parsed: List[Tuple[str, str]] = []
            for block in str(raw_list).split(";"):
                if not block:
                    continue
                try:
                    idx_str, name = block.split("^")
                    parsed.append((idx_str, name))
                except ValueError:
                    logger.warning("[OpenAPI] 조건식 파싱 실패: %s", block)
            if apply:
                self.conditions = parsed
                self.conditions_loaded = True
                head_preview = ", ".join([f"{i}:{n}" for i, n in parsed[:5]])
                tail_preview = ", ".join([f"{i}:{n}" for i, n in parsed[-5:]]) if len(parsed) > 5 else ""
                print(
                    f"[OpenAPI] 조건식 {len(self.conditions)}개 로딩 완료 head=[{head_preview}] tail=[{tail_preview}]"
                )
            return parsed

        def get_conditions(self) -> List[Tuple[str, str]]:
            if not self.conditions_loaded:
                return []
            return list(self.conditions)

        def get_condition_name_list(self) -> List[Tuple[int, str]]:
            return [(int(idx), name) for idx, name in self.get_conditions()]

        # -- Condition universe -----------------------------------------
        def allocate_screen_no(self, key: int) -> str:
            base = 5000
            offset = key % 800  # keep under 4 digits, avoid 0000
            screen = base + offset
            if screen % 10000 == 0:
                screen += 1
            return f"{screen:04d}"

        def send_condition(self, screen_no: str, condition_name: str, index: int, search_type: int = 1) -> int:
            """Run a condition by index/name and optionally register real-time (search_type=1)."""

            if not self.conditions_loaded:
                print("[OpenAPI] 조건식이 로딩되지 않았습니다.")
                return 0
            target = self.ax
            try:
                if target and hasattr(target, "dynamicCall"):
                    ret = target.dynamicCall(
                        "SendCondition(QString, QString, int, int)", screen_no, condition_name, int(index), int(search_type)
                    )
                    print(
                        f"[OpenAPI] SendCondition screen={screen_no} name={condition_name} index={index} search_type={search_type} ret={ret}"
                    )
                    if ret != 1:
                        print(
                            f"[OpenAPI][ERROR] SendCondition 실패 ret={ret} screen={screen_no} name={condition_name} index={index} search_type={search_type}"
                        )
                    return int(ret)
                raise RuntimeError("SendCondition 사용 불가")
            except Exception as exc:
                print(f"[OpenAPI] SendCondition 실패: {exc}")
                traceback.print_exc()
                return 0

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
                # clear cached server info so we always read the latest value after login
                self.server_gubun = ""
                raw = self.get_server_gubun_raw()
                self.server_gubun_changed.emit(raw)
                self.load_conditions()
                self.request_account_list()

        def _on_receive_condition_ver(self, lRet: int, sMsg: str) -> None:
            print(f"[OpenAPI] OnReceiveConditionVer ret={lRet} msg={sMsg}")
            if lRet == 1:
                previous_len = len(self.conditions)
                parsed = self.fetch_condition_list(apply=False)
                new_len = len(parsed)
                if previous_len > 0 and new_len < previous_len:
                    raw_str = "".join(traceback.format_stack(limit=4))
                    print(
                        f"[OpenAPI] IGNORE shorter condition list: new_len={new_len} old_len={previous_len}"
                    )
                    print(raw_str)
                    self._condition_load_requested = False
                    return
                self.conditions = parsed
                self.conditions_loaded = True
                head_preview = ", ".join([f"{i}:{n}" for i, n in parsed[:5]])
                tail_preview = ", ".join([f"{i}:{n}" for i, n in parsed[-5:]]) if len(parsed) > 5 else ""
                print(
                    f"[OpenAPI] 조건식 {len(self.conditions)}개 로딩 완료 head=[{head_preview}] tail=[{tail_preview}]"
                )
                self._condition_load_requested = False
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

        def _on_receive_real_data(self, code: str, real_type: str, _data: str) -> None:
            """Handle real-time price updates and broadcast a simplified payload."""

            if not self.ax:
                return
            try:
                price = float(str(self.ax.dynamicCall("GetCommRealData(QString,int)", code, 10)).strip() or 0)
                change = float(str(self.ax.dynamicCall("GetCommRealData(QString,int)", code, 11)).strip() or 0)
                change_rate_raw = str(self.ax.dynamicCall("GetCommRealData(QString,int)", code, 12)).strip()
                change_rate = float(change_rate_raw) if change_rate_raw else 0.0
                payload = {
                    "code": code,
                    "type": real_type,
                    "price": price,
                    "change": change,
                    "change_rate": change_rate,
                }
                if price:
                    self.last_prices[code] = price
                self.real_data_received.emit(code, payload)
            except Exception as exc:
                print(f"[OpenAPI] Failed to parse real data for {code}: {exc}")

        def _on_receive_chejan_data(self, gubun: str, item_cnt: int, fid_list: str) -> None:
            """Relay chejan(order/exec) events downstream."""

            payload: dict[str, object] = {
                "gubun": str(gubun),
                "item_cnt": int(item_cnt),
                "fid_list": str(fid_list),
            }
            try:
                ax = self.ax
                if ax and hasattr(ax, "dynamicCall"):
                    for fid in (9203, 9001, 302, 10, 904, 913):
                        try:
                            payload[str(fid)] = ax.dynamicCall("GetChejanData(int)", int(fid))
                        except Exception:
                            payload[str(fid)] = ""
                print(f"[OpenAPI] OnReceiveChejanData payload={payload}")
            except Exception as exc:  # pragma: no cover - runtime dependent
                print(f"[OpenAPI] Chejan 처리 실패: {exc}")
            if self.chejan_received:
                self.chejan_received.emit(payload)

        # -- Accounts / balances ----------------------------------------
        def request_account_list(self) -> None:
            if not self.is_enabled():
                return
            try:
                ax = self.ax
                raw_accounts = ""
                if ax and hasattr(ax, "dynamicCall"):
                    raw_accounts = str(ax.dynamicCall("GetLoginInfo(QString)", "ACCNO") or "")
                    gubun = str(ax.dynamicCall("GetLoginInfo(QString)", "GetServerGubun") or "")
                    self.server_gubun = gubun
                    print(f"[DEBUG] GetServerGubun raw={gubun!r} (request_account_list)")
                accounts = [acc for acc in raw_accounts.split(";") if acc]
                self.accounts = accounts
                print(f"[OpenAPI] 계좌 목록 {len(accounts)}건 로딩 완료: {accounts[:3]}")
                self.accounts_received.emit(accounts)
                self.server_gubun_changed.emit(self.server_gubun)
            except Exception as exc:  # pragma: no cover - runtime dependent
                print(f"[OpenAPI] 계좌 목록 조회 실패: {exc}")
                traceback.print_exc()

        def get_server_gubun(self) -> str:
            """Return Kiwoom server gubun (mock/real)."""

            if not self.is_enabled():
                return ""
            try:
                ax = self.ax
                raw = ""
                if ax and hasattr(ax, "dynamicCall"):
                    raw = str(ax.dynamicCall("GetLoginInfo(QString)", "GetServerGubun") or "")
                self.server_gubun = raw
            except Exception as exc:  # pragma: no cover
                print(f"[OpenAPI] GetServerGubun 실패: {exc}")
            return self.server_gubun

        def get_server_gubun_raw(self) -> str:
            raw = self.get_server_gubun()
            print(f"[DEBUG] GetServerGubun raw={raw!r}")
            return raw

        def is_simulation_server(self) -> bool:
            raw = self.get_server_gubun_raw()
            decision = raw == "1"
            print(f"[DEBUG] server_decision={'SIMULATION' if decision else 'REAL_OR_UNKNOWN'} raw={raw!r}")
            return decision

        # -- Ordering ----------------------------------------------------
        def send_order(
            self,
            rqname: str,
            screen_no: str,
            accno: str,
            order_type: int,
            code: str,
            qty: int,
            price: int,
            hogagb: str,
            org_order_no: str = "",
        ) -> bool:
            """Call the real SendOrder via dynamicCall.

            The actual result is delivered asynchronously through
            ``OnReceiveChejanData``. Returns ``True`` when the COM call was
            dispatched without raising.
            """

            if not self.is_enabled() or not self.connected:
                print("[OpenAPI] SendOrder 불가: 컨트롤 비활성 또는 미로그인")
                return False
            if self.is_simulation_server():
                print("[OpenAPI] SendOrder 차단: 현재 서버는 모의(raw=1)")
                return False
            try:
                ax = self.ax
                if not ax or not hasattr(ax, "dynamicCall"):
                    raise RuntimeError("QAxWidget dynamicCall 불가")
                print(
                    f"[OpenAPI] SendOrder rqname={rqname} screen={screen_no} accno={accno} "
                    f"type={order_type} code={code} qty={qty} price={price} hoga={hogagb} org={org_order_no}",
                    flush=True,
                )
                ax.dynamicCall(
                    "SendOrder(QString, QString, QString, int, QString, int, int, QString, QString)",
                    rqname,
                    screen_no,
                    accno,
                    int(order_type),
                    code,
                    int(qty),
                    int(price),
                    hogagb,
                    org_order_no,
                )
                return True
            except Exception as exc:  # pragma: no cover - runtime dependent
                print(f"[OpenAPI] SendOrder 실패: {exc}")
                traceback.print_exc()
                self.init_error = exc
                self._init_error = exc
                return False

        # -- Real-time price helpers -----------------------------------
        def set_real_reg(self, codes: List[str], fids: str = "10;11;12", screen_no: str = "9999") -> None:
            """Register real-time feeds for the given codes."""

            if not self.ax or not codes:
                return
            try:
                joined = ";".join(codes)
                self.ax.dynamicCall("SetRealReg(QString, QString, QString, QString)", screen_no, joined, fids, "0")
                print(f"[OpenAPI] SetRealReg screen={screen_no} codes={joined} fids={fids}")
            except Exception as exc:
                print(f"[OpenAPI] SetRealReg 실패: {exc}")

        def get_last_price(self, code: str) -> float:
            return float(self.last_prices.get(code, 0))

        def show_account_password_window(self) -> bool:
            """Open Kiwoom's account password window (ShowAccountWindow)."""

            if not self.is_enabled() or not (self.ax and hasattr(self.ax, "dynamicCall")):
                print("[OpenAPI] 계좌 비밀번호 창을 열 수 없습니다(ax 미활성)")
                return False
            if self._pw_window_shown:
                print("[OpenAPI] 계좌 비밀번호 창은 이미 한 번 열었습니다(세션 기준).")
                return False
            try:
                self.ax.dynamicCall("KOA_Functions(QString, QString)", "ShowAccountWindow", "")
                self._pw_window_shown = True
                print("[OpenAPI] 계좌비밀번호 입력창을 호출했습니다.")
                return True
            except Exception as exc:  # pragma: no cover - runtime dependent
                print(f"[OpenAPI] ShowAccountWindow 호출 실패: {exc}")
                traceback.print_exc()
                self._pw_window_shown = False
                return False

        def request_deposit_and_holdings(self, account_no: str, account_pw: str | None = None) -> bool:
            """Request deposit (opw00001) and holdings (opw00018).

            To avoid the (44) popup, ensure the Kiwoom password window has been
            opened at least once per session. When the window has not been
            shown, this method triggers it and asks the caller to retry after
            the user registers the password in Kiwoom.
            """

            if not self.is_enabled():
                print("[OpenAPI] 잔고 조회 불가: 컨트롤 비활성")
                return False

            if not self._pw_window_shown:
                opened = self.show_account_password_window()
                if opened:
                    print(
                        "[OpenAPI] 계좌비밀번호 입력창을 열었습니다. Kiwoom 창에서 비밀번호를 등록/닫은 뒤 다시 조회하세요."
                    )
                return False

            try:
                ax = self.ax
                if not (ax and hasattr(ax, "dynamicCall")):
                    print("[OpenAPI] dynamicCall 불가: ax 없음")
                    return False

                pw_value = account_pw or ""
                # opw00001 - deposit
                ax.dynamicCall("SetInputValue(QString, QString)", "계좌번호", account_no)
                ax.dynamicCall("SetInputValue(QString, QString)", "비밀번호", pw_value)
                ax.dynamicCall("SetInputValue(QString, QString)", "비밀번호입력매체구분", "00")
                ax.dynamicCall("SetInputValue(QString, QString)", "조회구분", "2")
                ax.dynamicCall(
                    "CommRqData(QString, QString, int, QString)",
                    "opw00001-balance",
                    "opw00001",
                    0,
                    self.screen_no,
                )
                # opw00018 - holdings
                ax.dynamicCall("SetInputValue(QString, QString)", "계좌번호", account_no)
                ax.dynamicCall("SetInputValue(QString, QString)", "비밀번호", pw_value)
                ax.dynamicCall("SetInputValue(QString, QString)", "비밀번호입력매체구분", "00")
                ax.dynamicCall("SetInputValue(QString, QString)", "상장폐지조회구분", "0")
                ax.dynamicCall(
                    "CommRqData(QString, QString, int, QString)",
                    "opw00018-holdings",
                    "opw00018",
                    0,
                    self.screen_no,
                )
                print(f"[OpenAPI] 잔고/보유 종목 조회 요청(opw00001/opw00018) account={account_no}")
                return True
            except Exception as exc:  # pragma: no cover
                print(f"[OpenAPI] 잔고/보유 종목 조회 요청 실패: {exc}")
                traceback.print_exc()
                if "44" in str(exc):
                    print(
                        "[조치] OpenAPI 트레이 아이콘 우클릭 → '계좌비밀번호 저장'에서 비밀번호 등록 후 다시 시도"
                    )
                    self._pw_window_shown = False
                return False

        def _on_receive_msg(self, screen_no, rqname, trcode, msg) -> None:
            print(f"[OpenAPI] OnReceiveMsg screen={screen_no} rqname={rqname} trcode={trcode} msg={msg}")
            if msg and "44" in str(msg):
                print("[OpenAPI] (44) 메시지 감지 → 비밀번호 창 재호출 가능 상태로 리셋")
                self._pw_window_shown = False

        def _on_receive_tr_data(self, *args) -> None:
            """Generic TR handler focusing on balance requests."""

            try:
                # Kiwoom TR signature varies; unpack defensively
                if len(args) >= 4:
                    screen_no, rqname, trcode, _record = args[:4]
                else:
                    print(f"[OpenAPI] OnReceiveTrData 인자 부족: {args}")
                    return
                rqname = str(rqname)
                trcode = str(trcode)
                print(f"[OpenAPI] OnReceiveTrData rqname={rqname} trcode={trcode}")

                if rqname == "opw00001-balance":
                    self._parse_balance(trcode, rqname)
                elif rqname == "opw00018-holdings":
                    self._parse_holdings(trcode, rqname)
            except Exception as exc:  # pragma: no cover
                print(f"[OpenAPI] OnReceiveTrData 처리 실패: {exc}")
                traceback.print_exc()

        def _parse_balance(self, trcode: str, rqname: str) -> None:
            """Parse opw00001 예수금상세현황요청 response."""

            try:
                ax = self.ax
                if not (ax and hasattr(ax, "dynamicCall")):
                    return
                cash_str = ax.dynamicCall("GetCommData(QString, QString, int, QString)", trcode, rqname, 0, "예수금")
                orderable_str = ax.dynamicCall(
                    "GetCommData(QString, QString, int, QString)", trcode, rqname, 0, "주문가능금액"
                )
                cash = int(str(cash_str).strip() or "0")
                orderable = int(str(orderable_str).strip() or "0")
                print(f"[OpenAPI] opw00001 수신: 예수금={cash} 주문가능={orderable}")
                self.balance_received.emit(cash, orderable)
            except Exception as exc:  # pragma: no cover
                print(f"[OpenAPI] 잔고 파싱 실패: {exc}")
                traceback.print_exc()
                if "44" in str(exc):
                    print("[조치] OpenAPI 트레이 아이콘 우클릭 → '계좌비밀번호 저장'에서 비밀번호 등록 후 다시 시도")

        def _parse_holdings(self, trcode: str, rqname: str) -> None:
            """Parse opw00018 보유 종목 내역."""

            holdings: List[dict] = []
            try:
                ax = self.ax
                if not (ax and hasattr(ax, "dynamicCall")):
                    return
                count = ax.dynamicCall("GetRepeatCnt(QString, QString)", trcode, rqname)
                try:
                    cnt = int(count)
                except Exception:
                    cnt = 0
                for i in range(cnt):
                    code = str(ax.dynamicCall("GetCommData(QString, QString, int, QString)", trcode, rqname, i, "종목코드")).strip()
                    name = str(ax.dynamicCall("GetCommData(QString, QString, int, QString)", trcode, rqname, i, "종목명")).strip()
                    qty = int(str(ax.dynamicCall("GetCommData(QString, QString, int, QString)", trcode, rqname, i, "보유수량")).strip() or "0")
                    avg_price = float(
                        str(ax.dynamicCall("GetCommData(QString, QString, int, QString)", trcode, rqname, i, "평균단가")).strip() or "0"
                    )
                    cur_price = float(
                        str(ax.dynamicCall("GetCommData(QString, QString, int, QString)", trcode, rqname, i, "현재가")).strip() or "0"
                    )
                    pnl_rate = float(
                        str(ax.dynamicCall("GetCommData(QString, QString, int, QString)", trcode, rqname, i, "수익률")).strip() or "0"
                    )
                    holdings.append(
                        {
                            "code": code,
                            "name": name,
                            "quantity": qty,
                            "avg_price": avg_price,
                            "current_price": cur_price,
                            "pnl_rate": pnl_rate,
                        }
                    )
                print(f"[OpenAPI] opw00018 수신: 보유종목 {len(holdings)}건")
                self.holdings_received.emit(holdings)
            except Exception as exc:  # pragma: no cover
                print(f"[OpenAPI] 보유종목 파싱 실패: {exc}")
                traceback.print_exc()
                if "44" in str(exc):
                    print("[조치] OpenAPI 트레이 아이콘 우클릭 → '계좌비밀번호 저장'에서 비밀번호 등록 후 다시 시도")


__all__ = ["KiwoomOpenAPI", "QAX_AVAILABLE"]
