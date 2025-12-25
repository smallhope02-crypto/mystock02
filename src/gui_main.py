"""PyQt5 GUI for the Mystock02 auto-trading playground."""

import datetime
import logging
import sys
from typing import List, Optional

try:
    from PyQt5.QtCore import Qt, QTimer, pyqtSlot, QSettings
    from PyQt5.QtWidgets import (
        QApplication,
        QButtonGroup,
        QCheckBox,
        QComboBox,
        QDialog,
        QDialogButtonBox,
        QDoubleSpinBox,
        QFormLayout,
        QGroupBox,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QListWidget,
        QListWidgetItem,
        QMainWindow,
        QMessageBox,
        QPushButton,
        QRadioButton,
        QSizePolicy,
        QSpinBox,
        QTableWidget,
        QTableWidgetItem,
        QTextEdit,
        QTimeEdit,
        QVBoxLayout,
        QWidget,
    )
except ImportError as exc:  # pragma: no cover - environment may lack PyQt5
    raise SystemExit("PyQt5 is required to run the GUI. Install it with 'pip install pyqt5'.") from exc

if sys.version_info < (3, 8):  # pragma: no cover - defensive guard for old installs
    raise SystemExit("Python 3.8+ is required to run the GUI. Please upgrade your interpreter.")

from .config import AppConfig, load_config
from .condition_manager import ConditionManager
from .kiwoom_client import KiwoomClient
from .kiwoom_openapi import KiwoomOpenAPI, QAX_AVAILABLE
from .selector import UniverseSelector
from .strategy import Strategy
from .trade_engine import TradeEngine

logger = logging.getLogger(__name__)


def _debug_combo_population(combo: QComboBox, src_items: List[str], label: str = "conditions") -> None:
    """Debug helper to log combo population counts and detect maxCount truncation."""

    try:
        normalized: List[str] = []
        for item in src_items or []:
            if isinstance(item, str):
                normalized.append(item)
            elif isinstance(item, (tuple, list)) and len(item) >= 2:
                normalized.append(f"{item[0]}: {item[1]}")
            elif isinstance(item, dict) and ("index" in item and "name" in item):
                normalized.append(f"{item['index']}: {item['name']}")
            else:
                normalized.append(str(item))

        src_len = len(normalized)
        max_count = combo.maxCount() if hasattr(combo, "maxCount") else None
        before_count = combo.count()
        print(
            f"[DEBUG] {label}: populate start src_len={src_len}, combo.maxCount={max_count}, before_count={before_count}, combo.objectName={combo.objectName()!r}"
        )

        if src_len:
            print(f"[DEBUG] {label}: SRC first='{normalized[0]}' | last='{normalized[-1]}'")

        combo.clear()
        combo.addItems(normalized)

        after_count = combo.count()
        print(f"[DEBUG] {label}: after addItems combo.count={after_count}, combo.maxCount={max_count}")

        if after_count:
            gui_first = combo.itemText(0)
            gui_last = combo.itemText(after_count - 1)
            print(f"[DEBUG] {label}: GUI first='{gui_first}' | last='{gui_last}'")

        if src_len and max_count and src_len > max_count and after_count == max_count:
            expected_first = normalized[-max_count]
            expected_last = normalized[-1]
            slice_match = (combo.itemText(0) == expected_first) and (combo.itemText(after_count - 1) == expected_last)
            print(f"[DEBUG] {label}: EXPECT slice[-{max_count}:] first='{expected_first}' | last='{expected_last}'")
            print(f"[DEBUG] {label}: slice_match={slice_match}")
            if slice_match:
                print(
                    f"[DEBUG] {label}: ✅ CONFIRMED: combo.maxCount({max_count}) 때문에 앞쪽 아이템이 삭제되어 '맨 끝 {max_count}개만' 남았습니다."
                )
            else:
                print(
                    f"[DEBUG] {label}: ⚠️ after_count==maxCount인데 slice_match가 False입니다. 다른 로직(슬라이싱/필터/정렬)도 의심하세요."
                )
    except Exception as exc:  # pragma: no cover - defensive debug helper
        print(f"[DEBUG] {label}: _debug_combo_population error: {exc!r}")


class ConfigDialog(QDialog):
    """Dialog to edit Kiwoom credentials and run connection checks."""

    def __init__(self, parent: QWidget, config: AppConfig, client: KiwoomClient, settings: QSettings, mode: str):
        super().__init__(parent)
        self.setWindowTitle("연동 설정")
        self.client = client
        self._config = config
        self._settings = settings
        self._mode = mode
        self.result_config: Optional[AppConfig] = None

        self.app_key_edit = QLineEdit(self._load_value("app_key", config.app_key))
        self.app_secret_edit = QLineEdit(self._load_value("app_secret", config.app_secret))
        self.app_secret_edit.setEchoMode(QLineEdit.Password)
        self.account_no_edit = QLineEdit(self._load_value("account_no", config.account_no))

        self.reload_btn = QPushButton("환경변수에서 다시 읽기")
        self.paper_login_btn = QPushButton("모의 로그인 테스트")
        self.real_login_btn = QPushButton("실거래 로그인 테스트")

        form = QFormLayout()
        form.addRow("App Key", self.app_key_edit)
        form.addRow("App Secret", self.app_secret_edit)
        form.addRow("Account No", self.account_no_edit)
        form.addRow(self.reload_btn)
        form.addRow(self.paper_login_btn)
        form.addRow(self.real_login_btn)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout()
        layout.addLayout(form)
        layout.addWidget(buttons)
        self.setLayout(layout)

        self.reload_btn.clicked.connect(self._reload_env)
        self.paper_login_btn.clicked.connect(self._test_paper_login)
        self.real_login_btn.clicked.connect(self._test_real_login)

    def _reload_env(self) -> None:
        cfg = load_config()
        self.app_key_edit.setText(cfg.app_key)
        self.app_secret_edit.setText(cfg.app_secret)
        self.account_no_edit.setText(cfg.account_no)
        self._save_values()

    def _test_paper_login(self) -> None:
        self._apply_to_client()
        success = self.client.login_paper()
        QMessageBox.information(self, "모의 로그인", "성공" if success else "실패")

    def _test_real_login(self) -> None:
        self._apply_to_client()
        success = self.client.login_real()
        QMessageBox.information(self, "실거래 로그인", "성공" if success else "실패")

    def _apply_to_client(self) -> None:
        cfg = AppConfig(
            app_key=self.app_key_edit.text(),
            app_secret=self.app_secret_edit.text(),
            account_no=self.account_no_edit.text(),
        )
        self.client.update_credentials(cfg)
        self._config = cfg
        self._save_values()

    def _on_accept(self) -> None:
        self._apply_to_client()
        self.result_config = self._config
        self.accept()

    # -- Settings helpers ----------------------------------------------
    def _key(self, name: str) -> str:
        return f"connection/{self._mode}/{name}"

    def _load_value(self, name: str, default: str) -> str:
        return str(self._settings.value(self._key(name), default))

    def _save_values(self) -> None:
        self._settings.setValue(self._key("app_key"), self.app_key_edit.text())
        self._settings.setValue(self._key("app_secret"), self.app_secret_edit.text())
        self._settings.setValue(self._key("account_no"), self.account_no_edit.text())
        self._settings.sync()


class MainWindow(QMainWindow):
    """PyQt window exposing trading controls, account info, and timers."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Mystock02 Auto Trader")

        self.settings = QSettings("Mystock02", "AutoTrader")
        self.current_config = load_config()
        self.strategy = Strategy()
        self.kiwoom_client = KiwoomClient(
            account_no=self.settings.value("connection/real/account_no", self.current_config.account_no),
            app_key=self.settings.value("connection/real/app_key", self.current_config.app_key),
            app_secret=self.settings.value("connection/real/app_secret", self.current_config.app_secret),
        )
        self.openapi_widget: Optional[KiwoomOpenAPI] = None
        if QAX_AVAILABLE:
            try:
                self.openapi_widget = KiwoomOpenAPI(self)
                self.kiwoom_client.attach_openapi(self.openapi_widget)
            except Exception as exc:  # pragma: no cover - GUI/runtime dependent
                print(f"[GUI] OpenAPI 위젯 생성 실패: {exc}")
        else:
            print("[GUI] QAxContainer 가 없어 OpenAPI 위젯을 생성하지 않습니다.")
        self.selector = UniverseSelector(kiwoom_client=self.kiwoom_client)
        self.engine = TradeEngine(
            strategy=self.strategy,
            selector=self.selector,
            broker_mode="paper",
            kiwoom_client=self.kiwoom_client,
        )
        self.condition_map = {}
        self.condition_manager = ConditionManager()
        self.condition_groups: list[dict[str, list[str]]] = []
        self.condition_universe: set[str] = set()
        self.enforce_market_hours: bool = True
        self.market_start = datetime.time(9, 0)
        self.market_end = datetime.time(15, 20)
        self._name_cache: dict[str, str] = {}
        self._price_cache: dict[str, float] = {}
        self._last_price_refresh_reason: str = ""
        self._saved_mode: str = "paper"
        self.real_holdings: list[dict] = []

        self.auto_timer = QTimer(self)
        self.auto_timer.timeout.connect(self._on_cycle)
        self.auto_timer.setInterval(5000)

        self.close_timer = QTimer(self)
        self.close_timer.timeout.connect(self._on_eod_check)
        self.close_timer.setInterval(30_000)
        self.close_timer.start()
        self.eod_executed_today: Optional[datetime.date] = None

        self._build_layout()
        self._connect_signals()
        if getattr(self.kiwoom_client, "openapi", None):
            print(
                "[GUI] KiwoomOpenAPI initial status:",
                self.kiwoom_client.openapi.debug_status(),
                flush=True,
            )
            # 상태가 비활성이라면 사용자 버튼 클릭 시 재초기화를 안내한다.
        self._load_settings()
        self._apply_mode_enable()
        self._refresh_condition_list()
        self._refresh_account()
        self._refresh_positions()
        self._update_connection_labels()

    # Layout helpers -----------------------------------------------------
    def _build_layout(self) -> None:
        root = QWidget()
        main = QVBoxLayout()

        # Connection group
        conn_group = QGroupBox("연결 / 모드 설정")
        conn_layout = QVBoxLayout()

        self.mode_group = QButtonGroup()
        self.paper_radio = QRadioButton("모의 모드")
        self.real_radio = QRadioButton("실거래 모드")
        self.paper_radio.setChecked(True)
        self.mode_group.addButton(self.paper_radio)
        self.mode_group.addButton(self.real_radio)

        radio_layout = QHBoxLayout()
        radio_layout.addWidget(self.paper_radio)
        radio_layout.addWidget(self.real_radio)

        self.config_btn = QPushButton("연동 설정")
        self.openapi_login_button = QPushButton("조건식 로그인")
        radio_layout.addWidget(self.config_btn)
        radio_layout.addWidget(self.openapi_login_button)

        conn_layout.addLayout(radio_layout)

        status_layout = QHBoxLayout()
        self.paper_status_label = QLabel()
        self.real_status_label = QLabel()
        status_layout.addWidget(self.paper_status_label)
        status_layout.addWidget(self.real_status_label)
        conn_layout.addLayout(status_layout)

        # Paper mode settings
        self.paper_group = QGroupBox("모의 모드 설정")
        paper_layout = QHBoxLayout()
        self.paper_cash_input = QDoubleSpinBox()
        self.paper_cash_input.setRange(100_000, 10_000_000_000)
        self.paper_cash_input.setDecimals(0)
        self.paper_cash_input.setPrefix("₩")
        paper_layout.addWidget(QLabel("모의 예수금"))
        paper_layout.addWidget(self.paper_cash_input)
        self.paper_balance_label = QLabel("모의 잔고(활성): -")
        paper_layout.addWidget(self.paper_balance_label)
        self.paper_group.setLayout(paper_layout)

        # Real mode settings
        self.real_group = QGroupBox("실거래 모드 설정")
        real_layout = QHBoxLayout()
        self.account_combo = QComboBox()
        self.account_combo.setPlaceholderText("계좌를 선택하세요")
        self.server_label = QLabel("서버: -")
        self.account_pw_input = QLineEdit()
        self.account_pw_input.setEchoMode(QLineEdit.Password)
        self.account_pw_input.setPlaceholderText("계좌 비밀번호(조회용)")
        self.real_balance_label = QLabel("실계좌 예수금: 실거래 모드에서만 표시")
        self.real_balance_label.setStyleSheet("color: gray;")
        self.real_balance_refresh = QPushButton("잔고 새로고침")
        real_layout.addWidget(QLabel("계좌"))
        real_layout.addWidget(self.account_combo)
        real_layout.addWidget(self.server_label)
        real_layout.addWidget(QLabel("비밀번호(조회)"))
        real_layout.addWidget(self.account_pw_input)
        real_layout.addWidget(self.real_balance_label)
        real_layout.addWidget(self.real_balance_refresh)
        self.real_group.setLayout(real_layout)

        conn_layout.addWidget(self.paper_group)
        conn_layout.addWidget(self.real_group)

        conn_group.setLayout(conn_layout)
        main.addWidget(conn_group)

        # Condition selector + group builder (group=OR, between groups=AND)
        cond_group = QGroupBox("조건식 선택 / 그룹 빌더")
        cond_layout = QHBoxLayout()

        self.condition_list = QListWidget()
        self.condition_list.setSelectionMode(QListWidget.MultiSelection)
        self.condition_list.setMinimumWidth(400)
        self.all_conditions: list[tuple[int, str]] = []
        self.refresh_conditions_btn = QPushButton("조건 새로고침")
        self.run_condition_btn = QPushButton("조건 실행(실시간 포함)")
        self.preview_candidates_btn = QPushButton("후보 보기")

        left_panel = QVBoxLayout()
        left_panel.addWidget(QLabel("조건식 목록"))
        left_panel.addWidget(self.condition_list)
        btn_row = QHBoxLayout()
        btn_row.addWidget(self.refresh_conditions_btn)
        btn_row.addWidget(self.run_condition_btn)
        btn_row.addWidget(self.preview_candidates_btn)
        left_panel.addLayout(btn_row)

        # Group builder
        right_panel = QVBoxLayout()
        right_panel.addWidget(QLabel("조건 그룹(내부 OR) / 그룹 간 AND"))
        self.group_list = QListWidget()
        self.group_list.setSelectionMode(QListWidget.SingleSelection)
        self.group_detail = QListWidget()
        self.group_detail.setSelectionMode(QListWidget.MultiSelection)
        self.group_preview_label = QLabel("(그룹 미구성)")
        self.group_preview_label.setStyleSheet("color: blue;")

        group_btn_row = QHBoxLayout()
        self.add_group_btn = QPushButton("그룹 추가")
        self.add_to_group_btn = QPushButton("선택 조건 → 그룹")
        self.remove_from_group_btn = QPushButton("그룹에서 제거")
        self.delete_group_btn = QPushButton("그룹 삭제")
        group_btn_row.addWidget(self.add_group_btn)
        group_btn_row.addWidget(self.add_to_group_btn)
        group_btn_row.addWidget(self.remove_from_group_btn)
        group_btn_row.addWidget(self.delete_group_btn)

        right_panel.addWidget(self.group_list)
        right_panel.addWidget(QLabel("선택 그룹 구성"))
        right_panel.addWidget(self.group_detail)
        right_panel.addLayout(group_btn_row)
        right_panel.addWidget(QLabel("조합 미리보기 (그룹 간 AND)"))
        right_panel.addWidget(self.group_preview_label)

        cond_layout.addLayout(left_panel)
        cond_layout.addLayout(right_panel)
        cond_group.setLayout(cond_layout)
        main.addWidget(cond_group)

        # Strategy parameters
        param_group = QGroupBox("전략 / 실행 설정")
        param_layout = QFormLayout()

        self.stop_loss_input = QDoubleSpinBox()
        self.stop_loss_input.setRange(0, 50)
        self.stop_loss_input.setSuffix(" %")
        self.stop_loss_input.setValue(self.strategy.stop_loss_pct * 100)

        self.take_profit_input = QDoubleSpinBox()
        self.take_profit_input.setRange(0, 100)
        self.take_profit_input.setSuffix(" %")
        self.take_profit_input.setValue(self.strategy.take_profit_pct * 100)

        self.trailing_input = QDoubleSpinBox()
        self.trailing_input.setRange(0, 50)
        self.trailing_input.setSuffix(" %")
        self.trailing_input.setValue(self.strategy.trailing_stop_pct * 100)

        self.time_limit_input = QSpinBox()
        self.time_limit_input.setRange(0, 600)
        self.time_limit_input.setValue(0)
        self.time_limit_input.setSuffix(" 분")

        self.max_pos_input = QSpinBox()
        self.max_pos_input.setRange(1, 50)
        self.max_pos_input.setValue(self.strategy.max_positions)

        self.apply_btn = QPushButton("전략 적용")
        self.apply_btn.setToolTip(
            "입력한 손절/트레일링/시간제한/최대 종목 수/모의 예수금을 전략에 반영만 합니다. 주문은 발생하지 않습니다."
        )

        self.test_btn = QPushButton("테스트 실행 (1회)")
        self.test_btn.setToolTip("현재 설정으로 매매 사이클을 1번만 실행합니다. 자동 반복은 하지 않습니다.")

        self.auto_start_btn = QPushButton("매수 시작 (자동)")
        self.auto_stop_btn = QPushButton("매수 종료 (자동)")

        self.dirty_label = QLabel("⚠ 전략 설정이 변경되었지만 아직 적용되지 않았습니다. [전략 적용]을 눌러주세요.")
        self.dirty_label.setStyleSheet("color: red;")
        self.dirty_label.hide()
        self.status_label = QLabel("상태: 대기중")

        self.eod_checkbox = QCheckBox("장 종료 전에 보유 종목 전량 청산")
        self.eod_time_edit = QTimeEdit()
        self.eod_time_edit.setDisplayFormat("HH:mm")
        self.eod_time_edit.setTime(datetime.time(15, 20))

        param_layout.addRow("손절률", self.stop_loss_input)
        param_layout.addRow("익절률", self.take_profit_input)
        param_layout.addRow("트레일링 스탑", self.trailing_input)
        param_layout.addRow("보유 시간 제한", self.time_limit_input)
        param_layout.addRow("최대 보유 종목 수", self.max_pos_input)
        param_layout.addRow(self.eod_checkbox, self.eod_time_edit)

        button_row = QHBoxLayout()
        button_row.addWidget(self.apply_btn)
        button_row.addWidget(self.test_btn)
        button_row.addWidget(self.auto_start_btn)
        button_row.addWidget(self.auto_stop_btn)

        param_layout.addRow(button_row)
        param_layout.addRow(self.dirty_label)
        param_layout.addRow(self.status_label)

        param_group.setLayout(param_layout)
        main.addWidget(param_group)

        # Positions and log
        self.positions_table = QTableWidget(0, 6)
        self.positions_table.setHorizontalHeaderLabels(["종목코드", "종목명", "수량", "진입가", "최고가", "현재가/등락"])
        main.addWidget(self.positions_table)

        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        main.addWidget(self.log_view)

        root.setLayout(main)
        self.setCentralWidget(root)

    def _connect_signals(self) -> None:
        self.paper_radio.toggled.connect(self.on_mode_changed)
        for widget in (
            self.stop_loss_input,
            self.take_profit_input,
            self.trailing_input,
            self.time_limit_input,
            self.max_pos_input,
        ):
            widget.valueChanged.connect(self._mark_dirty)
            widget.valueChanged.connect(lambda _=None: self._save_current_settings())
        self.paper_cash_input.valueChanged.connect(self._save_current_settings)

        self.apply_btn.clicked.connect(self.on_apply_strategy)
        self.test_btn.clicked.connect(self.on_run_once)
        self.auto_start_btn.clicked.connect(self.on_auto_start)
        self.auto_stop_btn.clicked.connect(self.on_auto_stop)
        self.config_btn.clicked.connect(self.on_open_config)
        self.openapi_login_button.clicked.connect(self._on_openapi_login)
        self.refresh_conditions_btn.clicked.connect(self._refresh_condition_list)
        self.run_condition_btn.clicked.connect(self._execute_condition)
        self.preview_candidates_btn.clicked.connect(self._preview_candidates)
        self.add_group_btn.clicked.connect(self._add_group)
        self.add_to_group_btn.clicked.connect(self._add_selected_to_group)
        self.remove_from_group_btn.clicked.connect(self._remove_from_group)
        self.delete_group_btn.clicked.connect(self._delete_group)
        self.group_list.currentRowChanged.connect(lambda _row: self._refresh_group_detail())
        self.real_balance_refresh.clicked.connect(self._refresh_real_balance)
        self.account_combo.currentTextChanged.connect(self._on_account_selected)
        if self.openapi_widget and hasattr(self.openapi_widget, "login_result"):
            self._log(
                f"[DEBUG] login_result signal object: {self.openapi_widget.login_result!r}"
            )
            try:
                self.openapi_widget.login_result.connect(self._on_openapi_login_result)
                self._log(
                    "[DEBUG] login_result 시그널을 _on_openapi_login_result 슬롯에 연결했습니다."
                )
            except TypeError as exc:
                # 일부 환경에서 시그니처 해석이 실패하는 경우 람다로 우회 연결
                self._log(
                    f"[WARN] login_result 직접 연결 실패: {exc}; lambda 어댑터로 재시도합니다."
                )
                try:
                    self.openapi_widget.login_result.connect(
                        lambda err: self._on_openapi_login_result(int(err))
                    )
                    self._log(
                        "[DEBUG] login_result 람다 어댑터로 슬롯 연결 성공"
                    )
                except Exception as inner:  # pragma: no cover - defensive
                    self._log(
                        f"[ERROR] login_result 연결 재시도 실패: {inner}; 시그니처를 확인하세요."
                    )
            except Exception as exc:
                self._log(
                    f"[ERROR] login_result 연결 실패: {exc}; 시그니처를 확인하세요."
                )
        if self.openapi_widget and hasattr(self.openapi_widget, "condition_ver_received"):
            self.openapi_widget.condition_ver_received.connect(
                self._on_openapi_condition_ver
            )
        if self.openapi_widget and hasattr(self.openapi_widget, "tr_condition_received"):
            self.openapi_widget.tr_condition_received.connect(self._on_tr_condition_received)
        if self.openapi_widget and hasattr(self.openapi_widget, "real_condition_received"):
            self.openapi_widget.real_condition_received.connect(self._on_real_condition_received)
        if self.openapi_widget:
            real_data_sig = getattr(self.openapi_widget, "real_data_received", None)
            if real_data_sig is not None and hasattr(real_data_sig, "connect"):
                real_data_sig.connect(self._on_real_data_received)
        if self.openapi_widget and hasattr(self.openapi_widget, "accounts_received"):
            self.openapi_widget.accounts_received.connect(self._on_accounts_received)
        if self.openapi_widget and hasattr(self.openapi_widget, "balance_received"):
            self.openapi_widget.balance_received.connect(self._on_balance_received)
        if self.openapi_widget and hasattr(self.openapi_widget, "holdings_received"):
            self.openapi_widget.holdings_received.connect(self._on_holdings_received)
        if self.openapi_widget and hasattr(self.openapi_widget, "server_gubun_changed"):
            self.openapi_widget.server_gubun_changed.connect(self._on_server_gubun_changed)

    # Settings ---------------------------------------------------------
    def _settings_mode(self) -> str:
        return "paper" if self.paper_radio.isChecked() else "real"

    def _load_settings(self) -> None:
        mode = self.settings.value("ui/mode", "paper")
        self._saved_mode = str(mode)
        if self._saved_mode == "real":
            self.real_radio.setChecked(True)
        else:
            self.paper_radio.setChecked(True)
        self._load_strategy_settings()
        self._apply_mode_enable()
        self._save_current_settings()

    def _load_strategy_settings(self) -> None:
        mode_prefix = f"strategy/{self._settings_mode()}/"
        def getf(key: str, default: float) -> float:
            val = self.settings.value(mode_prefix + key, default)
            try:
                return float(val)
            except Exception:
                return default

        def geti(key: str, default: int) -> int:
            val = self.settings.value(mode_prefix + key, default)
            try:
                return int(val)
            except Exception:
                return default

        stop = getf("stop_loss_pct", self.strategy.stop_loss_pct * 100)
        take = getf("take_profit_pct", self.strategy.take_profit_pct * 100)
        trail = getf("trailing_pct", self.strategy.trailing_stop_pct * 100)
        paper_cash = getf("paper_cash", self.strategy.initial_cash)
        max_pos = geti("max_positions", self.strategy.max_positions)
        eod_time = self.settings.value(mode_prefix + "eod_time", "15:20")

        self.stop_loss_input.blockSignals(True)
        self.take_profit_input.blockSignals(True)
        self.trailing_input.blockSignals(True)
        self.paper_cash_input.blockSignals(True)
        self.max_pos_input.blockSignals(True)
        try:
            self.stop_loss_input.setValue(stop)
            self.take_profit_input.setValue(take)
            self.trailing_input.setValue(trail)
            self.paper_cash_input.setValue(paper_cash)
            self.max_pos_input.setValue(max_pos)
            try:
                h, m = map(int, str(eod_time).split(":"))
                self.eod_time_edit.setTime(datetime.time(h, m))
            except Exception:
                pass
        finally:
            self.stop_loss_input.blockSignals(False)
            self.take_profit_input.blockSignals(False)
            self.trailing_input.blockSignals(False)
            self.paper_cash_input.blockSignals(False)
            self.max_pos_input.blockSignals(False)
        self._apply_parameters_from_controls()

    def _save_current_settings(self) -> None:
        mode = self._settings_mode()
        prefix = f"strategy/{mode}/"
        self.settings.setValue("ui/mode", mode)
        self.settings.setValue(prefix + "stop_loss_pct", self.stop_loss_input.value())
        self.settings.setValue(prefix + "take_profit_pct", self.take_profit_input.value())
        self.settings.setValue(prefix + "trailing_pct", self.trailing_input.value())
        self.settings.setValue(prefix + "paper_cash", self.paper_cash_input.value())
        self.settings.setValue(prefix + "max_positions", self.max_pos_input.value())
        self.settings.setValue(prefix + "eod_time", self.eod_time_edit.time().toString("HH:mm"))
        if mode == "real":
            self.settings.setValue("connection/real/account_no", self.account_combo.currentText())
        self.settings.sync()

    def _apply_mode_enable(self) -> None:
        mode = self._settings_mode()
        self.paper_group.setEnabled(mode == "paper")
        self.real_group.setEnabled(mode == "real")
        if mode == "paper":
            self.real_balance_label.setStyleSheet("color: gray;")
        else:
            self.real_balance_label.setStyleSheet("color: black;")

    def _apply_parameters_from_controls(self) -> None:
        params = dict(
            initial_cash=self.paper_cash_input.value(),
            max_positions=self.max_pos_input.value(),
            stop_loss_pct=self.stop_loss_input.value() / 100,
            take_profit_pct=self.take_profit_input.value() / 100,
            trailing_stop_pct=self.trailing_input.value() / 100,
        )
        self.strategy.update_parameters(**params)
        self.engine.set_paper_cash(self.paper_cash_input.value())

    def _update_server_label(self, gubun: str) -> None:
        text = f"서버: 알 수 없음(raw={gubun})"
        if gubun == "1":
            text = f"서버: 모의(raw={gubun})"
        elif gubun:
            text = f"서버: 실서버(raw={gubun})"
        self.server_label.setText(text)

    # Event handlers -----------------------------------------------------
    def on_mode_changed(self) -> None:
        mode = "paper" if self.paper_radio.isChecked() else "real"
        self.engine.set_mode(mode)
        if mode == "real":
            self.real_balance_label.setStyleSheet("color: black;")
        else:
            self.real_balance_label.setStyleSheet("color: gray;")
        if self.openapi_widget:
            self._update_server_label(self.openapi_widget.get_server_gubun())
        self._load_strategy_settings()
        self._refresh_account()
        self._update_connection_labels()
        self.status_label.setText("상태: 대기중")
        self._save_current_settings()

    def on_open_config(self) -> None:
        dialog = ConfigDialog(self, self.current_config, self.kiwoom_client, self.settings, self._settings_mode())
        if dialog.exec_() == QDialog.Accepted and dialog.result_config:
            self.current_config = dialog.result_config
            self.engine.update_credentials(self.current_config)
            self._update_connection_labels()

    def _on_openapi_login(self) -> None:
        try:
            self._log("[조건] 로그인 버튼 클릭 - OpenAPI 상태 확인")
            openapi = self.kiwoom_client.openapi
            if not openapi:
                self._log("[조건] OpenAPI 래퍼가 없습니다. (초기화 실패)")
                return
            print("[GUI] OpenAPI debug_status before init:", openapi.debug_status(), flush=True)
            openapi.initialize_control()
            print("[GUI] OpenAPI debug_status after init:", openapi.debug_status(), flush=True)
            if not openapi.is_enabled():
                self._log(
                    "[조건] OpenAPI 비활성 상태: " f"{openapi.debug_status()}"
                )
                self._log("조건식 기능을 사용할 수 없습니다. (OpenAPI 컨트롤 생성 실패)")
                return
            self._log("[조건] CommConnect 호출 시도")
            ok = openapi.connect_for_conditions()
            if not ok:
                err = getattr(openapi, "_init_error", None)
                self._log(f"[조건] CommConnect 호출 실패: {repr(err)}")
                self._log("조건식 기능을 사용할 수 없습니다. (CommConnect 호출 실패 – 콘솔 로그와 init_error를 확인하세요.)")
                return
            self._log(
                "[조건] CommConnect 호출 완료. 로그인 완료 여부는 OnEventConnect 이벤트 수신 후 결정됩니다."
            )
        except Exception as exc:  # pragma: no cover - defensive UI guard
            self._log(f"조건식 로그인 실패: {exc}")

    @pyqtSlot(int)
    def _on_openapi_login_result(self, err_code: int) -> None:
        if err_code == 0:
            self._log("[조건] OpenAPI 로그인 성공 - 조건식 로딩 진행")
            if self.openapi_widget:
                self.openapi_widget.request_account_list()
                raw = self.openapi_widget.get_server_gubun_raw()
                self._log(f"[DEBUG] GetServerGubun raw={raw!r} (login_result)")
                self._update_server_label(raw)
            self._refresh_condition_list()
        else:
            self._log(f"[조건] OpenAPI 로그인 실패 (코드 {err_code})")

    @pyqtSlot(int, str)
    def _on_openapi_condition_ver(self, ret: int, msg: str) -> None:
        self._log(f"[조건] 조건식 버전 수신 ret={ret} msg={msg}")

    @pyqtSlot(str, str, str, int, str)
    def _on_tr_condition_received(self, screen_no: str, code_list: str, condition_name: str, index: int, next_: str) -> None:
        if condition_name not in self.condition_manager.condition_sets:
            self._log(f"[조건] 무시: 활성 조건 목록에 없는 {condition_name}")
            return
        codes = [code for code in str(code_list).split(";") if code]
        self.condition_manager.update_condition(condition_name, codes)
        self._log(
            f"[조건] 초기 조회 결과 수신({condition_name}/{index}) - {len(codes)}건"
        )
        self._recompute_universe()

    @pyqtSlot(str, str, str, str)
    def _on_real_condition_received(self, code: str, event: str, condition_name: str, condition_index: str) -> None:
        if condition_name not in self.condition_manager.condition_sets:
            return
        self.condition_manager.apply_event(condition_name, code, event)
        action = "편입" if event == "I" else "편출" if event == "D" else f"기타({event})"
        self._log(
            f"[조건-실시간] {action}: {code} (조건 {condition_name}/{condition_index})"
        )
        self._recompute_universe()

    def _recompute_universe(self) -> None:
        final_set, group_sets = self.condition_manager.evaluate()
        counts = self.condition_manager.counts()
        group_sizes = [len(s) for s in group_sets]
        self.condition_universe = set(final_set)
        self.engine.set_external_universe(list(final_set))
        self._log(f"[GROUP] groups configured: {self._group_preview_text()}")
        self._log("[GROUP] evaluation rule: within-group=OR, between-groups=AND")
        self._log(
            f"[GROUP] set sizes: cond={counts} groups={group_sizes} final candidates={len(final_set)}"
        )
        openapi = getattr(self.kiwoom_client, "openapi", None)
        if openapi:
            openapi.set_real_reg(list(final_set))

    @pyqtSlot(list)
    def _on_accounts_received(self, accounts: list) -> None:
        self._log(f"[조건] 계좌 목록 수신: {len(accounts)}건")
        previous = self.account_combo.currentText()
        self.account_combo.clear()
        for acc in accounts:
            self.account_combo.addItem(acc)
        # restore saved selection if available
        saved = self.settings.value("real/account_no", "")
        if saved and saved in accounts:
            self.account_combo.setCurrentText(saved)
        elif previous in accounts:
            self.account_combo.setCurrentText(previous)
        self._save_current_settings()
        # 서버 구분 표시
        if self.openapi_widget:
            self._update_server_label(self.openapi_widget.get_server_gubun_raw())

    @pyqtSlot(int, int)
    def _on_balance_received(self, cash: int, orderable: int) -> None:
        self.real_balance_label.setStyleSheet("color: black;")
        self.real_balance_label.setText(f"실계좌 예수금(활성): {cash:,.0f}원 / 주문가능: {orderable:,.0f}원")
        self._log(f"[실거래] 예수금 수신: {cash:,.0f} / 주문가능 {orderable:,.0f}")

    @pyqtSlot(list)
    def _on_holdings_received(self, holdings: list) -> None:
        self.real_holdings = holdings
        self._log(f"[실거래] 보유종목 수신: {len(holdings)}건")
        self._refresh_positions(market_open=self._is_market_open())

    @pyqtSlot(str, dict)
    def _on_real_data_received(self, code: str, payload: dict) -> None:
        price = float(payload.get("price", 0) or 0)
        if price:
            self._price_cache[code] = price
        self._refresh_positions(market_open=self._is_market_open())

    @pyqtSlot(str)
    def _on_server_gubun_changed(self, raw: str) -> None:
        self._update_server_label(raw)
        decision = "SIMULATION" if raw == "1" else "REAL_OR_UNKNOWN"
        self._log(f"[DEBUG] GetServerGubun raw={raw!r}")
        self._log(f"[DEBUG] server_decision={decision} ui_mode={'REAL' if self.real_radio.isChecked() else 'SIM'}")
        if self.real_radio.isChecked() and decision == "SIMULATION":
            self._log(
                "[경고] 실거래 모드이지만 모의서버(raw='1')로 접속되어 실계좌 조회/주문이 차단됩니다. "
                "OpenAPI 로그아웃 후 실서버로 다시 로그인하세요."
            )

    def _on_account_selected(self, account: str) -> None:
        self._save_current_settings()
        if not account or self._settings_mode() != "real":
            return
        openapi = getattr(self.kiwoom_client, "openapi", None)
        if openapi:
            self._update_server_label(openapi.get_server_gubun())
        if openapi and hasattr(openapi, "request_deposit_and_holdings"):
            # 자동 조회는 하지 않고 새로고침 버튼을 유도
            return
        else:
            self._log("[실거래] 잔고 조회 불가: OpenAPI 컨트롤 없음")

    def _selected_conditions(self) -> list[tuple[int, str]]:
        selections: list[tuple[int, str]] = []
        for i in range(self.condition_list.count()):
            item = self.condition_list.item(i)
            if item.checkState() == Qt.Checked:
                data = item.data(Qt.UserRole)
                if data:
                    selections.append(data)
        return selections

    def _selected_condition_names(self) -> list[str]:
        return [name for _idx, name in self._selected_conditions()]

    # Condition group helpers -----------------------------------------
    def _group_preview_text(self) -> str:
        if not self.condition_groups:
            return "(그룹 없음)"
        parts: list[str] = []
        for g in self.condition_groups:
            conds = g.get("conditions", [])
            inner = " OR ".join(conds) if conds else "(empty)"
            parts.append(f"({g.get('name', 'Group')} : {inner})")
        return " AND ".join(parts)

    def _refresh_group_list(self) -> None:
        self.group_list.blockSignals(True)
        current = self.group_list.currentRow()
        self.group_list.clear()
        for g in self.condition_groups:
            conds = g.get("conditions", [])
            summary = ", ".join(conds) if conds else "(empty)"
            item = QListWidgetItem(f"{g.get('name', 'Group')}: {summary}")
            self.group_list.addItem(item)
        if 0 <= current < self.group_list.count():
            self.group_list.setCurrentRow(current)
        elif self.group_list.count():
            self.group_list.setCurrentRow(0)
        self.group_list.blockSignals(False)
        self._refresh_group_detail()
        self._update_group_preview()

    def _refresh_group_detail(self) -> None:
        idx = self.group_list.currentRow()
        self.group_detail.clear()
        if idx < 0 or idx >= len(self.condition_groups):
            return
        for name in self.condition_groups[idx].get("conditions", []):
            item = QListWidgetItem(name)
            item.setData(Qt.UserRole, name)
            self.group_detail.addItem(item)

    def _update_group_preview(self) -> None:
        self.group_preview_label.setText(self._group_preview_text())

    def _add_group(self) -> None:
        selections = self._selected_condition_names()
        if not selections:
            self._log("[GROUP] 그룹을 만들 조건식을 먼저 선택하세요.")
            return
        group_name = f"Group {len(self.condition_groups) + 1}"
        self.condition_groups.append({"name": group_name, "conditions": selections})
        self._log(f"[GROUP] 그룹 추가: {group_name} ← {selections}")
        self.condition_manager.set_groups([g["conditions"] for g in self.condition_groups])
        self.condition_manager.reset_sets()
        self._refresh_group_list()

    def _add_selected_to_group(self) -> None:
        idx = self.group_list.currentRow()
        if idx < 0 or idx >= len(self.condition_groups):
            self._log("[GROUP] 먼저 추가할 그룹을 선택하세요.")
            return
        selections = self._selected_condition_names()
        if not selections:
            self._log("[GROUP] 그룹에 넣을 조건식을 선택하세요.")
            return
        target = self.condition_groups[idx]
        added = []
        for name in selections:
            if name not in target["conditions"]:
                target["conditions"].append(name)
                added.append(name)
            else:
                self._log(f"[GROUP] {target['name']}에 이미 존재: {name}")
        if added:
            self._log(f"[GROUP] {target['name']}에 조건 추가: {added}")
        self.condition_manager.set_groups([g["conditions"] for g in self.condition_groups])
        self.condition_manager.reset_sets()
        self._refresh_group_list()

    def _remove_from_group(self) -> None:
        idx = self.group_list.currentRow()
        if idx < 0 or idx >= len(self.condition_groups):
            self._log("[GROUP] 제거할 그룹을 선택하세요.")
            return
        selected = [self.group_detail.item(i).data(Qt.UserRole) for i in range(self.group_detail.count()) if self.group_detail.item(i).isSelected()]
        if not selected:
            self._log("[GROUP] 그룹에서 제거할 조건을 선택하세요.")
            return
        before = len(self.condition_groups[idx]["conditions"])
        self.condition_groups[idx]["conditions"] = [c for c in self.condition_groups[idx]["conditions"] if c not in selected]
        after = len(self.condition_groups[idx]["conditions"])
        self._log(f"[GROUP] {self.condition_groups[idx]['name']}에서 {before - after}개 제거: {selected}")
        if not self.condition_groups[idx]["conditions"]:
            self._log("[GROUP] 그룹이 비었습니다. 실행 전에 채워주세요.")
        self.condition_manager.set_groups([g["conditions"] for g in self.condition_groups])
        self.condition_manager.reset_sets()
        self._refresh_group_list()

    def _delete_group(self) -> None:
        idx = self.group_list.currentRow()
        if idx < 0 or idx >= len(self.condition_groups):
            self._log("[GROUP] 삭제할 그룹을 선택하세요.")
            return
        removed = self.condition_groups.pop(idx)
        self._log(f"[GROUP] 그룹 삭제: {removed.get('name', '')}")
        self.condition_manager.set_groups([g["conditions"] for g in self.condition_groups])
        self.condition_manager.reset_sets()
        self._refresh_group_list()

    def _preview_candidates(self) -> None:
        if not self.condition_groups:
            self._log("[GROUP] 그룹이 없습니다. 그룹을 먼저 구성하세요.")
            return
        missing_group = [g for g in self.condition_groups if not g.get("conditions")]
        if missing_group:
            self._log("[GROUP] 비어있는 그룹이 있어 후보를 계산할 수 없습니다.")
            return
        final_set, group_sets = self.condition_manager.evaluate()
        cond_counts = self.condition_manager.counts()
        group_sizes = [len(s) for s in group_sets]
        self._log(
            f"[GROUP] evaluation rule: within-group=OR, between-groups=AND | cond_counts={cond_counts} | group_sizes={group_sizes} | final candidates={len(final_set)}"
        )
        self._update_group_preview()

    def _execute_condition(self) -> None:
        """Run the selected condition via OpenAPI (조회 + 실시간 등록)."""

        openapi = getattr(self.kiwoom_client, "openapi", None)
        if not openapi or not openapi.is_enabled():
            self._log("조건식 기능을 사용할 수 없습니다. (OpenAPI 컨트롤 생성 실패)")
            return
        if not openapi.connected:
            self._log("OpenAPI 로그인 후 조건식을 사용할 수 있습니다.")
            return
        if not openapi.conditions_loaded:
            self._log("조건식 정보가 아직 로드되지 않았습니다. 새로고침을 먼저 진행하세요.")
            openapi.load_conditions()
            return

        if not self.condition_groups:
            self._log("[GROUP] 그룹이 없습니다. 그룹을 먼저 구성하세요.")
            return
        if any(not g.get("conditions") for g in self.condition_groups):
            self._log("[GROUP] 비어있는 그룹이 있어 조건을 실행할 수 없습니다.")
            return

        active_conditions = sorted({name for g in self.condition_groups for name in g.get("conditions", [])})
        missing = [name for name in active_conditions if name not in self.condition_map]
        if missing:
            self._log(f"[GROUP] 조건식 정보가 존재하지 않습니다: {missing}")
            return

        self.condition_universe.clear()
        self.engine.set_external_universe([])
        self.condition_manager.set_groups([g["conditions"] for g in self.condition_groups])
        self.condition_manager.reset_sets()
        for name in active_conditions:
            idx, _ = self.condition_map[name]
            self._log(f"[조건] SendCondition 호출 - {name}({idx}), 실시간 등록 포함")
            try:
                screen_no = f"{openapi.screen_no}{idx}"
                openapi.send_condition(screen_no, name, idx, 1)
            except Exception as exc:  # pragma: no cover - runtime dependent
                self._log(f"조건 실행 실패({name}): {exc}")

        self._log(f"[GROUP] groups configured: {self._group_preview_text()}")
        self._log("[GROUP] evaluation rule: within-group=OR, between-groups=AND")

    def on_apply_strategy(self) -> None:
        params = dict(
            initial_cash=self.paper_cash_input.value(),
            max_positions=self.max_pos_input.value(),
            stop_loss_pct=self.stop_loss_input.value() / 100,
            take_profit_pct=self.take_profit_input.value() / 100,
            trailing_stop_pct=self.trailing_input.value() / 100,
        )
        self.strategy.update_parameters(**params)
        self.engine.set_paper_cash(self.paper_cash_input.value())
        self.dirty_label.hide()
        self.status_label.setText(
            f"전략 적용 완료 ({datetime.datetime.now().strftime('%H:%M:%S')})"
        )
        self._refresh_account()
        self._save_current_settings()

    def on_run_once(self) -> None:
        if self.engine.broker_mode == "real":
            proceed = QMessageBox.question(
                self,
                "실거래 테스트 실행",
                "실거래 계좌에서 실제 주문이 나갈 수 있습니다. 계속하시겠습니까?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if proceed != QMessageBox.Yes:
                return

        if self.enforce_market_hours and not self._is_market_open():
            now = datetime.datetime.now()
            self._log(
                f"[장시간] 매매 스킵: 장 시간이 아님 (now={now.strftime('%H:%M:%S')}, range={self.market_start}-{self.market_end})"
            )
            return

        if not self.condition_universe:
            self._log("[유니버스] 조건 결과가 없음(condition_universe empty) → 매매판단 스킵")
            return

        self.engine.set_external_universe(list(self.condition_universe))
        self._log(f"[유니버스] selector 사용 목록: external_universe 우선 적용 ({len(self.condition_universe)}건)")
        self.engine.run_once("combined")
        self._refresh_account()
        self._refresh_positions(market_open=self._is_market_open())
        self._log(f"테스트 실행 1회 완료 ({len(self.strategy.positions)}개 보유)")

    def on_auto_start(self) -> None:
        if not self.auto_timer.isActive():
            server_info = "-"
            openapi = getattr(self.kiwoom_client, "openapi", None)
            if openapi:
                server_info = openapi.get_server_gubun_raw()
            self._log(
                f"[자동매매] 시작 버튼 클릭 - mode={self.engine.broker_mode} server_gubun={server_info}"
            )
            if self.enforce_market_hours and not self._is_market_open():
                now = datetime.datetime.now()
                self._log(
                    f"[장시간] 매매 스킵: 장 시간이 아님 (now={now.strftime('%H:%M:%S')}, range={self.market_start}-{self.market_end})"
                )
                return
            self.auto_timer.start()
            self.status_label.setText("상태: 자동 매매 중 (매수 시작됨)")
            self._log("자동 매매 시작")

    def on_auto_stop(self) -> None:
        if self.auto_timer.isActive():
            self.auto_timer.stop()
            self.status_label.setText("상태: 매수 종료됨 (자동 정지)")
            self._log("자동 매매 정지")

    def _on_cycle(self) -> None:
        self._on_eod_check()
        if self.eod_executed_today == datetime.date.today():
            return
        now = datetime.datetime.now()
        if self.enforce_market_hours and not self._is_market_open():
            self._log(
                f"[장시간] 매매 스킵: 장 시간이 아님 (now={now.strftime('%H:%M:%S')}, range={self.market_start}-{self.market_end})"
            )
            self._refresh_positions(market_open=False)
            return
        if not self.condition_universe:
            self._log("[유니버스] 조건 결과가 없음(condition_universe empty) → 매매판단 스킵")
            self._refresh_positions(market_open=self._is_market_open())
            return
        self.engine.set_external_universe(list(self.condition_universe))
        self._log(f"[유니버스] selector 사용 목록: external_universe 우선 적용 ({len(self.condition_universe)}건)")
        self.engine.run_once("combined")
        self._refresh_account()
        self._refresh_positions(market_open=self._is_market_open())

    def _is_market_open(self) -> bool:
        now = datetime.datetime.now()
        if now.weekday() >= 5:  # 주말
            return False
        now_time = now.time()
        return self.market_start <= now_time <= self.market_end

    def _on_eod_check(self) -> None:
        if not self.eod_checkbox.isChecked():
            return
        now = datetime.datetime.now()
        target = datetime.datetime.combine(now.date(), self.eod_time_edit.time().toPyTime())
        if self.eod_executed_today == now.date():
            return
        if now >= target:
            self.engine.close_all_positions()
            self._refresh_account()
            self._refresh_positions()
            self.auto_timer.stop()
            self.eod_executed_today = now.date()
            self._log("장 종료 청산 실행 – 모든 포지션 매도 및 자동 매매 중지")
            self.status_label.setText("상태: 매수 종료됨 (장 종료 청산)")

    # Rendering helpers --------------------------------------------------
    def _mark_dirty(self) -> None:
        self.dirty_label.show()

    def _status_dot(self, ok: bool) -> str:
        color = "green" if ok else "red"
        text = "연결됨" if ok else "끊김"
        return f"<span style='color:{color};'>●</span> {text}"

    def _update_connection_labels(self) -> None:
        self.paper_status_label.setText(f"모의 연결 상태: {self._status_dot(self.kiwoom_client.is_connected_paper())}")
        self.real_status_label.setText(f"실거래 연결 상태: {self._status_dot(self.kiwoom_client.is_connected_real())}")

    def _refresh_account(self) -> None:
        if self.engine.broker_mode == "paper":
            summary = self.engine.account_summary()
            cash = summary.get("cash", 0)
            equity = summary.get("equity", 0)
            pnl = summary.get("pnl", 0)
            pnl_pct = 0
            if self.strategy.initial_cash:
                pnl_pct = (equity - self.strategy.initial_cash) / self.strategy.initial_cash * 100

            self.paper_balance_label.setText(
                f"모의 잔고(활성): {cash:,.0f} / 평가금액: {equity:,.0f} / 손익: {pnl:,.0f} ({pnl_pct:.2f}%)"
            )
            self.real_balance_label.setText("실계좌 예수금: 실거래 모드에서만 표시")
            self.real_balance_label.setStyleSheet("color: gray;")
        else:
            # 유지: 잔고는 OnReceiveTrData(opw00001)에서 갱신
            self.real_balance_label.setStyleSheet("color: black;")
            if "예수금(활성)" not in self.real_balance_label.text():
                self.real_balance_label.setText("실계좌 예수금: 잔고 새로고침을 누르세요")
            self.paper_balance_label.setText("모의 잔고: 모의 모드에서만 갱신")
        self._update_connection_labels()

    def _refresh_real_balance(self) -> None:
        if self.engine.broker_mode == "paper":
            self._refresh_account()
            self._log("모의 잔고를 새로고침했습니다.")
            return

        account = self.account_combo.currentText().strip()
        if not account:
            self._log("[실거래] 잔고 조회 불가: 계좌를 먼저 선택하세요.")
            return
        openapi = getattr(self.kiwoom_client, "openapi", None)
        if openapi:
            gubun = openapi.get_server_gubun_raw()
            self._update_server_label(gubun)
            if gubun == "1":
                self._log(
                    "[경고] 현재 OpenAPI가 모의서버로 연결(raw='1')되어 실계좌 조회/주문 불가. "
                    "실서버로 다시 로그인하세요 (로그아웃 후 로그인창에서 모의투자 체크 해제)."
                )
                return
            else:
                self._log(
                    f"[INFO] 서버 구분(raw={gubun!r}) 기반으로 실거래 잔고 조회를 진행합니다."
                )
        if openapi and hasattr(openapi, "request_deposit_and_holdings") and openapi.connected:
            pw = self.account_pw_input.text().strip()
            if not pw:
                self._log("[실거래] 잔고 조회 불가: 계좌 비밀번호(조회용)를 입력하세요. (팝업 방지)")
                return
            openapi.request_deposit_and_holdings(account, pw)
            self._log(f"[실거래] 잔고/보유종목 TR 요청(account={account})")
        else:
            self._log("[실거래] 잔고 조회 불가: OpenAPI 컨트롤 없음 또는 미로그인")

    def _get_symbol_name(self, code: str) -> str:
        if code in self._name_cache:
            return self._name_cache[code]
        try:
            name = self.kiwoom_client.get_master_name(code)
        except Exception as exc:  # pragma: no cover - GUI fallback
            self._log(f"[시세] 종목명 조회 실패({code}): {exc}")
            name = f"UNKNOWN-{code}"
        self._name_cache[code] = name
        return name

    def _refresh_positions(self, market_open: Optional[bool] = None) -> None:
        if market_open is None:
            market_open = self._is_market_open()

        use_real_holdings = self.engine.broker_mode == "real" and self.real_holdings
        positions = list(self.strategy.positions.values())
        self.positions_table.setRowCount(len(self.real_holdings) if use_real_holdings else len(positions))
        price_refresh_reason = ""

        if use_real_holdings:
            openapi = getattr(self.kiwoom_client, "openapi", None)
            if openapi:
                openapi.set_real_reg([h.get("code", "") for h in self.real_holdings if h.get("code")])
            for row, h in enumerate(self.real_holdings):
                code = h.get("code", "").strip()
                name = h.get("name", "") or self._get_symbol_name(code)
                qty = h.get("quantity", 0)
                avg_price = float(h.get("avg_price", 0) or 0)
                cur_price = float(h.get("current_price", 0) or 0)
                pnl_rate = float(h.get("pnl_rate", 0) or 0)
                change_text = f"{cur_price:.2f} / {pnl_rate:.2f}%"
                self.positions_table.setItem(row, 0, QTableWidgetItem(code))
                self.positions_table.setItem(row, 1, QTableWidgetItem(name))
                self.positions_table.setItem(row, 2, QTableWidgetItem(str(qty)))
                self.positions_table.setItem(row, 3, QTableWidgetItem(f"{avg_price:.2f}"))
                self.positions_table.setItem(row, 4, QTableWidgetItem(f"{max(cur_price, avg_price):.2f}"))
                self.positions_table.setItem(row, 5, QTableWidgetItem(change_text))
        else:
            for row, pos in enumerate(positions):
                name = self._get_symbol_name(pos.symbol)
                current_price = None
                change_text = "--"
                if not market_open:
                    price_refresh_reason = "[시세] 장전이라 시세 갱신을 건너뜁니다."
                else:
                    try:
                        current_price = self._price_cache.get(pos.symbol) or self.engine.get_current_price(
                            pos.symbol
                        )
                        if current_price and pos.entry_price:
                            change_pct = (current_price - pos.entry_price) / pos.entry_price * 100
                            change_text = f"{current_price:.2f} / {change_pct:.2f}%"
                        elif current_price:
                            change_text = f"{current_price:.2f}"
                    except Exception as exc:  # pragma: no cover - defensive
                        price_refresh_reason = f"[시세] 실시간 시세 조회 실패({pos.symbol}): {exc}"

                self.positions_table.setItem(row, 0, QTableWidgetItem(pos.symbol))
                self.positions_table.setItem(row, 1, QTableWidgetItem(name))
                self.positions_table.setItem(row, 2, QTableWidgetItem(str(pos.quantity)))
                self.positions_table.setItem(row, 3, QTableWidgetItem(f"{pos.entry_price:.2f}"))
                self.positions_table.setItem(row, 4, QTableWidgetItem(f"{pos.highest_price:.2f}"))
                self.positions_table.setItem(row, 5, QTableWidgetItem(change_text))

        if price_refresh_reason and price_refresh_reason != self._last_price_refresh_reason:
            self._log(price_refresh_reason)
            self._last_price_refresh_reason = price_refresh_reason
        elif market_open and not price_refresh_reason:
            self._last_price_refresh_reason = ""

        self.positions_table.resizeColumnsToContents()

    def _refresh_condition_list(self) -> None:
        openapi = getattr(self.kiwoom_client, "openapi", None)
        if not openapi or not openapi.is_enabled():
            self.condition_list.clear()
            self.condition_map.clear()
            self._log("조건식 기능을 사용할 수 없습니다. (OpenAPI 비활성)")
            return
        if not openapi.connected:
            self.condition_list.clear()
            self.condition_map.clear()
            self._log("OpenAPI 로그인 후 조건식을 사용할 수 있습니다.")
            return
        if not openapi.conditions_loaded:
            self.condition_list.clear()
            self.condition_map.clear()
            openapi.load_conditions()
            self._log("조건식 정보를 불러오는 중입니다...")
            return

        try:
            conditions = openapi.get_conditions()
        except Exception as exc:  # pragma: no cover - UI fallback
            self._log(f"조건식 목록 조회 실패: {exc}")
            conditions = []

        raw_count = len(conditions)
        preview_head = ", ".join([f"{c[0]}:{c[1]}" for c in conditions[:3]])
        preview_tail = ", ".join([f"{c[0]}:{c[1]}" for c in conditions[-3:]]) if raw_count > 3 else ""
        self._log(f"[COND] loaded {raw_count} conditions head=[{preview_head}] tail=[{preview_tail}]")

        self.condition_list.clear()
        self.condition_map.clear()
        self.all_conditions = [(int(idx), name) for idx, name in conditions]
        for idx, name in self.all_conditions:
            item = QListWidgetItem(f"{idx}: {name}")
            item.setData(Qt.UserRole, (idx, name))
            item.setCheckState(Qt.Unchecked)
            self.condition_list.addItem(item)
            self.condition_map[name] = (idx, name)

        valid_names = {name for _, name in self.all_conditions}
        pruned = False
        for g in self.condition_groups:
            before = len(g["conditions"])
            g["conditions"] = [c for c in g["conditions"] if c in valid_names]
            if len(g["conditions"]) != before:
                pruned = True
        if pruned:
            self._log("[GROUP] 일부 그룹 구성에 더 이상 존재하지 않는 조건식이 있어 제거했습니다.")
        self.condition_manager.set_groups([g["conditions"] for g in self.condition_groups])
        self._refresh_group_list()

    def _log(self, message: str) -> None:
        self.log_view.append(message)
        logger.info(message)


def main(argv: Optional[List[str]] = None) -> None:
    """Entry point for manual GUI testing."""

    app = QApplication(argv or [])
    window = MainWindow()
    window.show()
    app.exec_()


if __name__ == "__main__":
    main()
