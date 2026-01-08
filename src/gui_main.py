"""PyQt5 GUI for the Mystock02 auto-trading playground."""

import datetime
import json
import logging
import sys
import time
from typing import List, Optional, Sequence

try:
    from PyQt5.QtCore import Qt, QTimer, pyqtSlot, QSettings
    from PyQt5.QtWidgets import (
        QApplication,
        QAbstractScrollArea,
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
        QInputDialog,
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
from .paper_broker import PaperBroker
from .selector import UniverseSelector
from .strategy import Strategy
from .trade_engine import TradeEngine
from .trade_history_store import TradeHistoryStore
from .universe_diag import classify_universe_empty
from .gui_trade_history import TradeHistoryDialog

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
        self.history_store = TradeHistoryStore()
        self.current_config = load_config()
        self.strategy = Strategy()
        self.kiwoom_client = KiwoomClient(
            account_no=self.settings.value("connection/real/account_no", self.current_config.account_no),
            app_key=self.settings.value("connection/real/app_key", self.current_config.app_key),
            app_secret=self.settings.value("connection/real/app_secret", self.current_config.app_secret),
            history_store=self.history_store,
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
        paper_broker = PaperBroker(initial_cash=self.strategy.initial_cash, history_store=self.history_store)
        self.engine = TradeEngine(
            strategy=self.strategy,
            selector=self.selector,
            broker_mode="paper",
            kiwoom_client=self.kiwoom_client,
            paper_broker=paper_broker,
            log_fn=self._log,
        )
        self.engine.set_buy_limits(rebuy_after_sell_today=False, max_buy_per_symbol_today=1)
        self.condition_map = {}
        self.condition_screens: dict[str, str] = {}
        self.condition_manager = ConditionManager()
        self.builder_tokens: list[dict] = []
        self.condition_universe: set[str] = set()
        self.condition_universe_today: set[str] = set()
        self.enforce_market_hours: bool = True
        self.market_start = datetime.time(9, 0)
        self.market_end = datetime.time(15, 20)
        self.auto_trading_active: bool = False
        self.auto_trading_armed: bool = False
        self.trading_orders_enabled: bool = False
        self._name_cache: dict[str, str] = {}
        self._price_cache: dict[str, float] = {}
        self._last_price_refresh_reason: str = ""
        self._saved_mode: str = "paper"
        self.real_holdings: list[dict] = []
        self._last_market_log: Optional[datetime.datetime] = None
        self._last_market_reason: str = ""
        self._last_open_flag: Optional[bool] = None
        self._pending_trigger_name: str = ""
        self._pending_today_candidates: list[str] = []
        self._pending_preset_state: Optional[dict] = None
        self._pending_preset_name: str = str(self.settings.value("builder/last_preset", "") or "")
        self._last_universe_diag: dict = {}
        self._last_cond_event_ts: float | None = None
        self._warned_no_cond_event: bool = False

        self.auto_timer = QTimer(self)
        self.auto_timer.timeout.connect(self._on_cycle)
        self.auto_timer.setInterval(5000)

        self.close_timer = QTimer(self)
        self.close_timer.timeout.connect(self._on_eod_check)
        self.close_timer.setInterval(30_000)
        self.close_timer.start()
        self.eod_executed_today: Optional[datetime.date] = None

        self._build_layout()
        self._load_preset_list()
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
        self.history_button = QPushButton("매수/매도 이력")
        radio_layout.addWidget(self.config_btn)
        radio_layout.addWidget(self.openapi_login_button)
        radio_layout.addWidget(self.history_button)

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
        self.account_pw_input.setPlaceholderText("세션 메모리만 사용(저장하지 않음)")
        self.account_pw_input.setToolTip("실거래 잔고 조회용 비밀번호(세션 메모리만 사용)")
        # OpenAPI 비밀번호 입력창으로 유도하는 버튼(직접 비밀번호는 저장하지 않음)
        self.account_pw_button = QPushButton("계좌비밀번호 저장 (키움 창 열기)")
        self.real_order_checkbox = QCheckBox("실주문 활성화")
        self.real_balance_label = QLabel("실계좌 예수금: 실거래 모드에서만 표시")
        self.real_balance_label.setStyleSheet("color: gray;")
        self.real_balance_refresh = QPushButton("잔고 새로고침")
        real_layout.addWidget(QLabel("계좌"))
        real_layout.addWidget(self.account_combo)
        real_layout.addWidget(self.server_label)
        real_layout.addWidget(QLabel("계좌 비밀번호(세션)"))
        real_layout.addWidget(self.account_pw_input)
        real_layout.addWidget(self.account_pw_button)
        real_layout.addWidget(self.real_order_checkbox)
        real_layout.addWidget(self.real_balance_label)
        real_layout.addWidget(self.real_balance_refresh)
        self.real_group.setLayout(real_layout)

        conn_layout.addWidget(self.paper_group)
        conn_layout.addWidget(self.real_group)

        conn_group.setLayout(conn_layout)
        main.addWidget(conn_group)

        # Condition selector + expression builder (group=OR buckets, between groups=AND)
        cond_group = QGroupBox("조건식 선택 / 그룹 빌더")
        cond_layout = QHBoxLayout()

        self.condition_list = QListWidget()
        self.condition_list.setSelectionMode(QListWidget.MultiSelection)
        self.condition_list.setMinimumWidth(400)
        self.all_conditions: list[tuple[int, str]] = []
        self.trigger_combo = QComboBox()
        self.trigger_combo.addItem("(사용 안 함)", "")
        self.today_candidate_list = QListWidget()
        self.today_candidate_list.setSelectionMode(QListWidget.MultiSelection)
        self.refresh_conditions_btn = QPushButton("조건 새로고침")
        self.run_condition_btn = QPushButton("조건 실행(실시간 포함)")
        self.preview_candidates_btn = QPushButton("후보 보기")
        self.gate_after_trigger_checkbox = QCheckBox("트리거 발생 후 오늘누적 포함")
        self.gate_after_trigger_checkbox.setChecked(False)
        self.allow_premarket_monitor_checkbox = QCheckBox("장전 감시 허용(주문은 장중)")
        self.allow_premarket_monitor_checkbox.setChecked(True)

        left_panel = QVBoxLayout()
        left_panel.addWidget(QLabel("조건식 목록"))
        left_panel.addWidget(self.condition_list)
        btn_row = QHBoxLayout()
        btn_row.addWidget(self.refresh_conditions_btn)
        btn_row.addWidget(self.run_condition_btn)
        btn_row.addWidget(self.preview_candidates_btn)
        left_panel.addLayout(btn_row)
        gate_layout = QFormLayout()
        gate_layout.addRow("트리거 조건", self.trigger_combo)
        gate_layout.addRow("오늘누적 후보", self.today_candidate_list)
        gate_layout.addRow(self.gate_after_trigger_checkbox)
        gate_layout.addRow(self.allow_premarket_monitor_checkbox)
        left_panel.addLayout(gate_layout)

        # Expression builder strip
        right_panel = QVBoxLayout()
        right_panel.addWidget(QLabel("조건 표현식 편집 (0150 스타일: 숫자/AND/OR/괄호)"))
        preset_row = QHBoxLayout()
        preset_row.addWidget(QLabel("프리셋"))
        self.preset_combo = QComboBox()
        self.preset_save_btn = QPushButton("저장")
        self.preset_load_btn = QPushButton("불러오기")
        self.preset_delete_btn = QPushButton("삭제")
        preset_row.addWidget(self.preset_combo)
        preset_row.addWidget(self.preset_save_btn)
        preset_row.addWidget(self.preset_load_btn)
        preset_row.addWidget(self.preset_delete_btn)
        right_panel.addLayout(preset_row)
        self.builder_strip = QListWidget()
        self.builder_strip.setSelectionMode(QListWidget.ExtendedSelection)
        self.builder_strip.setMinimumHeight(140)
        self.builder_strip.setSizeAdjustPolicy(QAbstractScrollArea.AdjustIgnored)
        self.builder_strip.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.builder_strip.setUniformItemSizes(True)

        builder_btn_row = QHBoxLayout()
        self.add_selected_btn = QPushButton("선택 추가(AND 체인)")
        self.wrap_btn = QPushButton("괄호로 감싸기")
        self.validate_btn = QPushButton("문법 검증")
        self.clear_builder_btn = QPushButton("초기화")
        builder_btn_row.addWidget(self.add_selected_btn)
        builder_btn_row.addWidget(self.wrap_btn)
        builder_btn_row.addWidget(self.validate_btn)
        builder_btn_row.addWidget(self.clear_builder_btn)

        self.group_preview_label = QLabel("(표현식 미구성)")
        self.group_preview_label.setStyleSheet("color: blue;")
        self.group_preview_label.setWordWrap(True)
        self.group_preview_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        self.group_preview_label.setMaximumWidth(700)

        right_panel.addWidget(self.builder_strip)
        right_panel.addLayout(builder_btn_row)
        right_panel.addWidget(QLabel("조합 미리보기 (표현식 그대로 표시)"))
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

        self.buy_order_mode_combo = QComboBox()
        self.buy_order_mode_combo.addItem("시장가(즉시체결)", "market")
        self.buy_order_mode_combo.addItem("지정가(호가이동)", "limit")
        self.buy_price_offset_ticks = QSpinBox()
        self.buy_price_offset_ticks.setRange(-50, 50)
        self.buy_price_offset_ticks.setValue(0)
        self.buy_price_offset_ticks.setSuffix(" 틱")

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
        param_layout.addRow("매수 주문 방식", self.buy_order_mode_combo)
        param_layout.addRow("매수 호가 이동(틱)", self.buy_price_offset_ticks)
        param_layout.addRow(self.eod_checkbox, self.eod_time_edit)
        self.rebuy_after_sell_checkbox = QCheckBox("오늘 매수 종목 매도 후 재매수 허용")
        self.max_buy_per_symbol_spin = QSpinBox()
        self.max_buy_per_symbol_spin.setRange(0, 10)
        self.max_buy_per_symbol_spin.setValue(1)
        param_layout.addRow(self.rebuy_after_sell_checkbox, QLabel("(기본 OFF)"))
        param_layout.addRow("종목별 최대 매수 횟수(오늘)", self.max_buy_per_symbol_spin)

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
            self.buy_price_offset_ticks,
        ):
            widget.valueChanged.connect(self._mark_dirty)
            widget.valueChanged.connect(lambda _=None: self._save_current_settings())
        self.paper_cash_input.valueChanged.connect(self._save_current_settings)
        self.buy_order_mode_combo.currentIndexChanged.connect(self._on_buy_order_mode_changed)

        self.apply_btn.clicked.connect(self.on_apply_strategy)
        self.test_btn.clicked.connect(self.on_run_once)
        self.auto_start_btn.clicked.connect(self.on_auto_start)
        self.auto_stop_btn.clicked.connect(self.on_auto_stop)
        self.config_btn.clicked.connect(self.on_open_config)
        self.openapi_login_button.clicked.connect(self._on_openapi_login)
        self.history_button.clicked.connect(self._open_trade_history)
        self.refresh_conditions_btn.clicked.connect(self._refresh_condition_list)
        self.run_condition_btn.clicked.connect(self._execute_condition)
        self.preview_candidates_btn.clicked.connect(self._preview_candidates)
        self.add_selected_btn.clicked.connect(self._on_add_selected_conditions)
        self.wrap_btn.clicked.connect(self._wrap_selection)
        self.validate_btn.clicked.connect(self._validate_builder)
        self.clear_builder_btn.clicked.connect(self._clear_builder)
        self.preset_save_btn.clicked.connect(self._on_save_preset)
        self.preset_load_btn.clicked.connect(self._on_load_preset)
        self.preset_delete_btn.clicked.connect(self._on_delete_preset)
        self.trigger_combo.currentIndexChanged.connect(self._save_current_settings)
        self.today_candidate_list.itemChanged.connect(lambda *_: self._save_current_settings())
        self.gate_after_trigger_checkbox.toggled.connect(self._save_current_settings)
        self.allow_premarket_monitor_checkbox.toggled.connect(self._save_current_settings)
        self.rebuy_after_sell_checkbox.toggled.connect(self._on_buy_limit_changed)
        self.max_buy_per_symbol_spin.valueChanged.connect(self._on_buy_limit_changed)
        self.builder_strip.itemDoubleClicked.connect(self._toggle_operator_token)
        self.real_order_checkbox.toggled.connect(self._on_real_order_toggled)
        self.real_balance_refresh.clicked.connect(self._refresh_real_balance)
        self.account_pw_button.clicked.connect(self._open_account_pw_window)
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
        if self.openapi_widget and hasattr(self.openapi_widget, "password_required"):
            self.openapi_widget.password_required.connect(self._on_password_required)

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
        self._load_universe_settings()
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
        self.buy_order_mode_combo.blockSignals(True)
        self.buy_price_offset_ticks.blockSignals(True)
        try:
            self.stop_loss_input.setValue(stop)
            self.take_profit_input.setValue(take)
            self.trailing_input.setValue(trail)
            self.paper_cash_input.setValue(paper_cash)
            self.max_pos_input.setValue(max_pos)
            mode_val = self.settings.value(mode_prefix + "buy_order_mode", "market")
            offset_val = geti("buy_offset_ticks", 0)
            idx = self.buy_order_mode_combo.findData(mode_val)
            if idx >= 0:
                self.buy_order_mode_combo.setCurrentIndex(idx)
            self.buy_price_offset_ticks.setValue(offset_val)
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
            self.buy_order_mode_combo.blockSignals(False)
            self.buy_price_offset_ticks.blockSignals(False)
        self.buy_price_offset_ticks.setEnabled(self.buy_order_mode_combo.currentData() == "limit")
        self._apply_parameters_from_controls()

    def _load_universe_settings(self) -> None:
        prefix = "universe/"
        trigger = self.settings.value(prefix + "trigger", "")
        today_raw = self.settings.value(prefix + "today_candidates", "") or ""
        today_candidates = [x for x in str(today_raw).split(",") if x]
        gate = self.settings.value(prefix + "gate_after_trigger", False, type=bool)
        premarket = self.settings.value(prefix + "allow_premarket", True, type=bool)
        rebuy = self.settings.value(prefix + "rebuy_after_sell", False, type=bool)
        max_buy = self.settings.value(prefix + "max_buy_per_symbol_today", 1)
        try:
            max_buy = int(max_buy)
        except Exception:
            max_buy = 1
        self.gate_after_trigger_checkbox.setChecked(bool(gate))
        self.allow_premarket_monitor_checkbox.setChecked(bool(premarket))
        self.rebuy_after_sell_checkbox.setChecked(bool(rebuy))
        self.max_buy_per_symbol_spin.setValue(max_buy)
        self._restore_condition_choices(trigger, today_candidates)
        self._on_buy_limit_changed()

    def _save_current_settings(self) -> None:
        mode = self._settings_mode()
        prefix = f"strategy/{mode}/"
        self.settings.setValue("ui/mode", mode)
        self.settings.setValue(prefix + "stop_loss_pct", self.stop_loss_input.value())
        self.settings.setValue(prefix + "take_profit_pct", self.take_profit_input.value())
        self.settings.setValue(prefix + "trailing_pct", self.trailing_input.value())
        self.settings.setValue(prefix + "paper_cash", self.paper_cash_input.value())
        self.settings.setValue(prefix + "max_positions", self.max_pos_input.value())
        self.settings.setValue(prefix + "buy_order_mode", self.buy_order_mode_combo.currentData())
        self.settings.setValue(prefix + "buy_offset_ticks", self.buy_price_offset_ticks.value())
        self.settings.setValue(prefix + "eod_time", self.eod_time_edit.time().toString("HH:mm"))
        if mode == "real":
            self.settings.setValue("connection/real/account_no", self.account_combo.currentText())
        # universe / gating
        uni_prefix = "universe/"
        self.settings.setValue(uni_prefix + "trigger", self.trigger_combo.currentData())
        selected_today = [
            item.data(Qt.UserRole)
            for i in range(self.today_candidate_list.count())
            if (item := self.today_candidate_list.item(i)).checkState() == Qt.Checked
        ]
        self.settings.setValue(uni_prefix + "today_candidates", ",".join([s for s in selected_today if s]))
        self.settings.setValue(uni_prefix + "gate_after_trigger", self.gate_after_trigger_checkbox.isChecked())
        self.settings.setValue(uni_prefix + "allow_premarket", self.allow_premarket_monitor_checkbox.isChecked())
        self.settings.setValue(uni_prefix + "rebuy_after_sell", self.rebuy_after_sell_checkbox.isChecked())
        self.settings.setValue(uni_prefix + "max_buy_per_symbol_today", self.max_buy_per_symbol_spin.value())
        self.settings.sync()

    def _apply_mode_enable(self) -> None:
        mode = self._settings_mode()
        self.paper_group.setEnabled(mode == "paper")
        self.real_group.setEnabled(mode == "real")
        if mode == "paper":
            self.real_balance_label.setStyleSheet("color: gray;")
            self.account_pw_input.setEnabled(False)
        else:
            self.real_balance_label.setStyleSheet("color: black;")
            self.account_pw_input.setEnabled(True)

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
        self._apply_pricing_params()

    def _apply_pricing_params(self) -> None:
        mode = self.buy_order_mode_combo.currentData()
        offset = self.buy_price_offset_ticks.value()
        self.engine.set_buy_pricing(mode, offset)

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
        if mode == "paper":
            self.real_order_checkbox.setChecked(False)
        if self.openapi_widget:
            self._update_server_label(self.openapi_widget.get_server_gubun())
        self._load_strategy_settings()
        self._refresh_account()
        self._update_connection_labels()
        self.status_label.setText("상태: 대기중")
        self._save_current_settings()

    def _on_real_order_toggled(self, checked: bool) -> None:
        if not checked:
            self._log("[주문] 실주문 비활성화")
            return
        text, ok = QInputDialog.getText(
            self,
            "실주문 활성화 확인",
            "실제 주문을 보내려면 '실주문'을 입력하세요:",
        )
        if not ok or text.strip() != "실주문":
            self._log("[주문] 확인 문구 불일치로 실주문 비활성화")
            self.real_order_checkbox.setChecked(False)
            return
        self._log("[주문] 실주문 활성화됨 — 장시간/서버 검증 후에만 SendOrder 호출")

    def _on_buy_limit_changed(self) -> None:
        self.engine.set_buy_limits(
            rebuy_after_sell_today=self.rebuy_after_sell_checkbox.isChecked(),
            max_buy_per_symbol_today=self.max_buy_per_symbol_spin.value(),
        )
        self._save_current_settings()

    def _on_buy_order_mode_changed(self) -> None:
        mode = self.buy_order_mode_combo.currentData()
        offset = self.buy_price_offset_ticks.value()
        self.buy_price_offset_ticks.setEnabled(mode == "limit")
        self.engine.set_buy_pricing(mode, offset)
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
        codes = [code for code in str(code_list).split(";") if code]
        name_key = condition_name
        if condition_name not in self.condition_manager.condition_sets_rt:
            alt = condition_name.strip()
            active = list(self.condition_manager.condition_sets_rt.keys())
            if alt != condition_name and alt in self.condition_manager.condition_sets_rt:
                self._log(f"[조건] condition_name normalize: '{condition_name}' -> '{alt}'")
                name_key = alt
            else:
                self._log(
                    f"[조건][WARN] 수신된 조건({condition_name})이 활성 목록에 없습니다. active={active}"
                )
        self.condition_manager.update_condition(name_key, codes)
        label = self._condition_id_text(name_key)
        self._log(
            f"[COND_EVT] 초기 조회 결과 수신 cond={name_key}({label}) idx={index} count={len(codes)}"
        )
        self._last_cond_event_ts = time.time()
        self._warned_no_cond_event = False
        self._recompute_universe()

    @pyqtSlot(str, str, str, str)
    def _on_real_condition_received(self, code: str, event: str, condition_name: str, condition_index: str) -> None:
        name_key = condition_name
        if condition_name not in self.condition_manager.condition_sets_rt:
            alt = condition_name.strip()
            if alt in self.condition_manager.condition_sets_rt:
                self._log(f"[조건] condition_name normalize: '{condition_name}' -> '{alt}' (real)")
                name_key = alt
            else:
                return
        self.condition_manager.apply_event(name_key, code, event)
        action = "편입" if event == "I" else "편출" if event == "D" else f"기타({event})"
        label = self._condition_id_text(name_key)
        self._log(
            f"[COND_EVT] {action}: {code} (조건 {name_key}/{label}/{condition_index})"
        )
        self._last_cond_event_ts = time.time()
        self._warned_no_cond_event = False
        self._recompute_universe()

    def _recompute_universe(self) -> None:
        final_set = self._evaluate_universe(log_prefix="EVAL")
        self.engine.set_external_universe(list(final_set))
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

    @pyqtSlot(str)
    def _on_password_required(self, message: str) -> None:
        self._log(f"[실거래] {message}")

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

    def _selected_today_candidates(self) -> list[str]:
        names: list[str] = []
        for i in range(self.today_candidate_list.count()):
            item = self.today_candidate_list.item(i)
            if item.checkState() == Qt.Checked:
                data = item.data(Qt.UserRole)
                if data:
                    names.append(str(data))
        return names

    def _selected_condition_names(self) -> list[str]:
        return [name for _idx, name in self._selected_conditions()]

    def _condition_id_text(self, name: str) -> str:
        if name in self.condition_map:
            idx, _ = self.condition_map[name]
            return str(idx)
        return name

    def _active_condition_names(self) -> list[str]:
        seen: list[str] = []
        for tok in self.builder_tokens:
            if tok.get("type") == "COND":
                name = str(tok.get("value"))
                if name and name not in seen:
                    seen.append(name)
        return seen

    # Condition builder helpers --------------------------------------
    def _builder_log_tokens(self) -> None:
        pretty = self.condition_manager.render_infix(self.builder_tokens)
        self._log(f"[BUILDER] tokens: {pretty if pretty else '(empty)'}")

    # Preset helpers ----------------------------------------------------
    def _preset_names(self) -> list[str]:
        names = self.settings.value("builder/presets", []) or []
        if isinstance(names, str):
            names = [names]
        return [str(n) for n in names]

    def _load_preset_list(self) -> None:
        names = self._preset_names()
        self.preset_combo.blockSignals(True)
        self.preset_combo.clear()
        for name in names:
            self.preset_combo.addItem(name)
        if self._pending_preset_name and self._pending_preset_name in names:
            self.preset_combo.setCurrentText(self._pending_preset_name)
        self.preset_combo.blockSignals(False)
        if self._pending_preset_name and not self._pending_preset_state:
            raw = self.settings.value(f"builder/preset/{self._pending_preset_name}", "")
            if raw:
                try:
                    state = json.loads(raw)
                    if self.condition_list.count() == 0:
                        self._pending_preset_state = state
                    else:
                        self._apply_preset_state(state, name=self._pending_preset_name)
                except Exception:
                    self._log(f"[프리셋][WARN] '{self._pending_preset_name}' 자동 적용 실패(JSON)")

    def _serialize_preset_state(self) -> dict:
        return {
            "checked_conditions": self._selected_condition_names(),
            "trigger": self.trigger_combo.currentData(),
            "today_candidates": self._selected_today_candidates(),
            "gate_after_trigger": self.gate_after_trigger_checkbox.isChecked(),
            "allow_premarket": self.allow_premarket_monitor_checkbox.isChecked(),
            "builder_tokens": self.builder_tokens,
        }

    def _apply_preset_state(self, state: dict, name: str | None = None) -> None:
        if self.condition_list.count() == 0:
            self._pending_preset_state = state
            self._pending_preset_name = name or self._pending_preset_name
            self._log("[프리셋] 조건 목록이 아직 없습니다. 새로고침 후 자동 적용합니다.")
            return
        checked = set(state.get("checked_conditions", []))
        for i in range(self.condition_list.count()):
            item = self.condition_list.item(i)
            data = item.data(Qt.UserRole)
            name_val = data[1] if data else ""
            item.setCheckState(Qt.Checked if name_val in checked else Qt.Unchecked)
        trigger_val = state.get("trigger", "")
        idx = self.trigger_combo.findData(trigger_val)
        if idx >= 0:
            self.trigger_combo.setCurrentIndex(idx)
        today_set = set(state.get("today_candidates", []))
        for i in range(self.today_candidate_list.count()):
            item = self.today_candidate_list.item(i)
            data = item.data(Qt.UserRole)
            item.setCheckState(Qt.Checked if data in today_set else Qt.Unchecked)
        self.gate_after_trigger_checkbox.setChecked(bool(state.get("gate_after_trigger", False)))
        self.allow_premarket_monitor_checkbox.setChecked(bool(state.get("allow_premarket", True)))
        tokens = state.get("builder_tokens", []) or []
        if isinstance(tokens, list):
            self.builder_tokens = list(tokens)
            self.condition_manager.set_expression_tokens(self.builder_tokens, reset_sets=True)
            self._refresh_builder_strip()
        if name:
            self.settings.setValue("builder/last_preset", name)
            self.settings.sync()

    def _on_save_preset(self) -> None:
        names = self._preset_names()
        default_name = self.preset_combo.currentText() or "preset1"
        name, ok = QInputDialog.getText(self, "프리셋 이름", "저장할 프리셋 이름:", text=default_name)
        if not ok or not name.strip():
            return
        name = name.strip()
        if name in names:
            confirm = QMessageBox.question(
                self,
                "덮어쓰기 확인",
                f"이미 존재하는 프리셋 '{name}' 를 덮어쓸까요?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if confirm != QMessageBox.Yes:
                return
        state = self._serialize_preset_state()
        try:
            payload = json.dumps(state, ensure_ascii=False)
            self.settings.setValue(f"builder/preset/{name}", payload)
            updated = [n for n in names if n != name] + [name]
            self.settings.setValue("builder/presets", updated)
            self.settings.setValue("builder/last_preset", name)
            self.settings.sync()
            self._pending_preset_name = name
            self._load_preset_list()
            self._log(f"[프리셋] '{name}' 저장 완료")
        except Exception as exc:  # pragma: no cover - defensive
            self._log(f"[프리셋][ERROR] 저장 실패: {exc}")

    def _on_load_preset(self) -> None:
        name = self.preset_combo.currentText().strip()
        if not name:
            self._log("[프리셋] 불러올 항목을 선택하세요.")
            return
        raw = self.settings.value(f"builder/preset/{name}", "")
        if not raw:
            self._log(f"[프리셋] '{name}' 데이터를 찾을 수 없습니다.")
            return
        try:
            state = json.loads(raw)
        except Exception as exc:  # pragma: no cover - user data
            self._log(f"[프리셋][ERROR] JSON 파싱 실패({name}): {exc}")
            return
        self._pending_preset_state = None
        self._pending_preset_name = name
        self._apply_preset_state(state, name=name)
        self._log(f"[프리셋] '{name}' 적용 완료")

    def _on_delete_preset(self) -> None:
        name = self.preset_combo.currentText().strip()
        if not name:
            return
        confirm = QMessageBox.question(
            self,
            "프리셋 삭제",
            f"'{name}' 프리셋을 삭제할까요?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return
        names = [n for n in self._preset_names() if n != name]
        self.settings.remove(f"builder/preset/{name}")
        self.settings.setValue("builder/presets", names)
        if self.settings.value("builder/last_preset", "") == name:
            self.settings.setValue("builder/last_preset", "")
        self.settings.sync()
        self._load_preset_list()
        self._log(f"[프리셋] '{name}' 삭제")

    def _refresh_builder_strip(self) -> None:
        self.builder_strip.blockSignals(True)
        self.builder_strip.clear()
        for token in self.builder_tokens:
            text = token.get("text") or token.get("value") or ""
            item = QListWidgetItem(text)
            if token["type"] == "OP":
                item.setForeground(Qt.blue)
            elif token["type"] in {"LPAREN", "RPAREN"}:
                item.setForeground(Qt.darkGreen)
            item.setData(Qt.UserRole, token)
            tooltip = token.get("tooltip") or token.get("value")
            if tooltip:
                item.setToolTip(str(tooltip))
            self.builder_strip.addItem(item)
        self.builder_strip.blockSignals(False)
        self._update_group_preview()

    def _clear_builder(self) -> None:
        self.builder_tokens = []
        self.condition_manager.set_expression_tokens([], reset_sets=True)
        self._refresh_builder_strip()
        self._log("[BUILDER] cleared")

    def _current_insert_index(self) -> int:
        idx = self.builder_strip.currentRow()
        return len(self.builder_tokens) if idx < 0 else idx

    def _insert_with_auto_and(self, idx: int, new_tokens: List[dict]) -> None:
        tokens = self.builder_tokens
        if tokens and idx > 0:
            prev = tokens[idx - 1]
            if prev["type"] in {"COND", "RPAREN"}:
                if idx == len(tokens) or tokens[idx]["type"] != "OP":
                    tokens.insert(idx, {"type": "OP", "value": "AND", "text": "AND"})
                    idx += 1
        for token in new_tokens:
            tokens.insert(idx, token)
            idx += 1
        self._refresh_builder_strip()
        self._update_expression_from_tokens(reset_sets=True)

    def _on_add_selected_conditions(self) -> None:
        selections = self._selected_conditions()
        if not selections:
            self._log("[BUILDER] 추가할 조건식을 선택하세요.")
            return
        # preserve display order in list
        selected_nums: list[int] = []
        selected_names: list[str] = []
        for i in range(self.condition_list.count()):
            item = self.condition_list.item(i)
            if item.checkState() == Qt.Checked:
                data = item.data(Qt.UserRole)
                if data and data not in selections:
                    # ensure same identity
                    pass
                if data:
                    idx, name = data
                    selected_nums.append(idx)
                    selected_names.append(name)
        if not selected_nums:
            for idx, name in selections:
                selected_nums.append(idx)
                selected_names.append(name)

        new_tokens: List[dict] = []
        for i, (cond_id, name) in enumerate(zip(selected_nums, selected_names)):
            if i > 0:
                new_tokens.append({"type": "OP", "value": "AND", "text": "AND"})
            new_tokens.append(
                {
                    "type": "COND",
                    "value": name,
                    "text": str(cond_id),
                    "tooltip": name,
                }
            )

        insert_at = self._current_insert_index()
        join_txt = "AND"
        self._log(f"[BUILDER] add_selected: nums={selected_nums} join={join_txt} insert_at={insert_at}")
        self._insert_with_auto_and(insert_at, new_tokens)
        self._builder_log_tokens()

    def _toggle_operator_token(self, item: QListWidgetItem) -> None:
        token = item.data(Qt.UserRole)
        if not token or token.get("type") != "OP":
            return

        row = self.builder_strip.row(item)
        if row < 0 or row >= len(self.builder_tokens):
            return

        old = self.builder_tokens[row].get("value")
        new_val = "OR" if old == "AND" else "AND"
        # Update the single source of truth first.
        self.builder_tokens[row]["value"] = new_val
        self.builder_tokens[row]["text"] = new_val

        # Keep the QListWidget item in sync with the token dict.
        item.setText(new_val)
        item.setData(Qt.UserRole, self.builder_tokens[row])

        self._log(f"[BUILDER] toggled operator idx={row}: {old} -> {new_val}")
        # Re-evaluate expression so preview/ConditionManager stay aligned.
        self._update_expression_from_tokens(reset_sets=False)
        self._builder_log_tokens()

    def _wrap_selection(self) -> None:
        rows = sorted({i for i in range(self.builder_strip.count()) if self.builder_strip.item(i).isSelected()})
        if not rows:
            self._log("[BUILDER] 괄호로 감쌀 토큰을 선택하세요.")
            return
        start, end = rows[0], rows[-1]
        self.builder_tokens.insert(start, {"type": "LPAREN", "value": "(", "text": "("})
        self.builder_tokens.insert(end + 2, {"type": "RPAREN", "value": ")", "text": ")"})
        self._log(f"[BUILDER] wrap tokens range {start}-{end}")
        self._refresh_builder_strip()
        self._update_expression_from_tokens(reset_sets=False)
        self._builder_log_tokens()

    def _validate_builder(self) -> bool:
        tokens = self.builder_tokens
        if not tokens:
            self._log("[BUILDER] 토큰이 비어있습니다.")
            return False
        depth = 0
        prev_type = None
        for token in tokens:
            ttype = token.get("type")
            if ttype == "LPAREN":
                depth += 1
            elif ttype == "RPAREN":
                depth -= 1
                if depth < 0:
                    self._log("[BUILDER] 닫는 괄호가 많습니다.")
                    return False
            elif ttype == "OP" and prev_type in (None, "OP", "LPAREN"):
                self._log("[BUILDER] 연속 연산자 또는 선행 연산자 오류")
                return False
            prev_type = ttype
        if depth != 0:
            self._log("[BUILDER] 괄호 짝이 맞지 않습니다.")
            return False
        if tokens[-1].get("type") == "OP":
            self._log("[BUILDER] 마지막 토큰이 연산자입니다.")
            return False
        self._log("[BUILDER] 문법 검증 OK")
        return True

    def _update_expression_from_tokens(self, reset_sets: bool = False) -> None:
        if not self.builder_tokens:
            self.condition_manager.set_expression_tokens([], reset_sets=False)
            if reset_sets:
                self.condition_manager.reset_sets()
            self._log("[EXPR] builder empty -> expression cleared")
            self._update_group_preview()
            return
        if not self._validate_builder():
            return
        self.condition_manager.set_expression_tokens(self.builder_tokens, reset_sets=reset_sets)
        # Log a quick snapshot of the current expression/postfix so UI and evaluator stay transparent.
        candidates, postfix = self.condition_manager.evaluate()
        infix_txt = self.condition_manager.render_infix(self.builder_tokens)
        postfix_txt = self.condition_manager.postfix_text(postfix)
        self._log(
            f"[EXPR] infix='{infix_txt}' postfix='{postfix_txt}' candidates={len(candidates)}"
        )
        self._update_group_preview()

    # Backward-compatibility wrapper for legacy callers.
    def _update_groups_from_tokens(self, reset_sets: bool = False) -> None:
        self._update_expression_from_tokens(reset_sets=reset_sets)

    def _group_preview_text(self) -> str:
        return self.condition_manager.render_infix(self.builder_tokens)

    def _update_group_preview(self) -> None:
        self.group_preview_label.setText(self._group_preview_text())

    def _evaluate_universe(self, log_prefix: str = "EVAL") -> set[str]:
        # Ensure we have an expression: if empty, auto-build OR chain from selected conditions
        if not self.builder_tokens:
            selected = self._selected_conditions()
            if selected:
                auto_tokens: list[dict] = []
                for idx, (_cid, name) in enumerate(selected):
                    auto_tokens.append(
                        {
                            "type": "COND",
                            "value": name,
                            "text": self._condition_id_text(name),
                            "tooltip": name,
                        }
                    )
                    if idx < len(selected) - 1:
                        auto_tokens.append({"type": "OP", "value": "OR", "text": "OR", "tooltip": "OR"})
                self.builder_tokens = auto_tokens
                self._refresh_builder_strip()
                self._log("[EVAL] builder empty → 자동 OR 구성으로 대체")
        # Evaluate RT expression
        self.condition_manager.set_expression_tokens(self.builder_tokens, reset_sets=False)
        rt_set, postfix = self.condition_manager.evaluate(source="rt")
        postfix_txt = self.condition_manager.postfix_text(postfix)
        infix = self.condition_manager.render_infix(self.builder_tokens)

        # Today cumulative buckets
        today_names = self._selected_today_candidates()
        today_union: set[str] = set()
        today_counts = {}
        for name in today_names:
            bucket = self.condition_manager.get_bucket(name, source="today")
            today_union |= bucket
            today_counts[name] = len(bucket)

        trigger_name = self.trigger_combo.currentData()
        trigger_hits = self.condition_manager.get_bucket(trigger_name, source="today") if trigger_name else set()
        gate_on = self.gate_after_trigger_checkbox.isChecked()
        gate_ok = True
        gate_reason = ""
        if gate_on and trigger_name and not trigger_hits:
            gate_ok = False
            gate_reason = "gate_not_satisfied"
        final_set = set(rt_set)
        if today_union and gate_ok:
            final_set |= today_union
        self.condition_universe_today = today_union if gate_ok else set()
        self.condition_universe = final_set
        rt_counts = self.condition_manager.counts()
        diag = {
            "infix": infix,
            "postfix": postfix_txt,
            "active_conditions": [t.get("value") for t in self.builder_tokens if t.get("type") == "COND"],
            "rt_counts": rt_counts,
            "today_counts": today_counts,
            "trigger_name": trigger_name,
            "trigger_hits_count": len(trigger_hits),
            "gate_on": gate_on,
            "gate_ok": gate_ok,
            "gate_reason": gate_reason,
            "rt_set_count": len(rt_set),
            "today_union_count": len(today_union),
            "final_set_count": len(final_set),
        }
        self._last_universe_diag = diag
        self._log(
            f"[{log_prefix}] infix={infix} postfix={postfix_txt} rt_count={len(rt_set)} rt_counts={rt_counts} today_union={len(today_union)} gate_on={gate_on} gate_ok={gate_ok} gate_reason={gate_reason} final={len(final_set)}"
        )
        if not final_set:
            reason, message = classify_universe_empty(diag)
            diag["reason"] = reason
            diag["message"] = message
            self._log(
                f"[유니버스] condition_universe empty reason={reason} trigger_seen={len(trigger_hits)}>0 today_union={len(today_union)}"
            )
            self._log(f"[유니버스] {message}")
            self._log(f"[유니버스][diag] {json.dumps(diag, ensure_ascii=False)}")
        return final_set

    def _preview_candidates(self) -> None:
        if not self._validate_builder():
            return
        final_set = self._evaluate_universe(log_prefix="EVAL")
        sample = list(final_set)[:10]
        self._log(f"[EVAL] candidates={len(final_set)} sample={sample}")
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

        if not self._validate_builder():
            return

        active_conditions = self._active_condition_names()
        missing = [name for name in active_conditions if name not in self.condition_map]
        if missing:
            self._log(f"[GROUP] 조건식 정보가 존재하지 않습니다: {missing}")
            return

        self.condition_universe.clear()
        self.engine.set_external_universe([])
        self.condition_manager.set_expression_tokens(self.builder_tokens, reset_sets=True)
        infix = self.condition_manager.render_infix(self.builder_tokens)
        self._log(f"[EXPR] infix={infix}")
        self._builder_log_tokens()
        open_flag, reason, now = self._market_state()
        if self.enforce_market_hours and not open_flag:
            self._log(
                f"[조건] 실행/등록 시작 (장전: register_only=True, 주문 차단) reason={reason}"
            )
        for name in active_conditions:
            idx, _ = self.condition_map[name]
            try:
                screen_no = openapi.allocate_screen_no(idx) if hasattr(openapi, "allocate_screen_no") else openapi.screen_no
                self.condition_screens[name] = screen_no
                ret = openapi.send_condition(screen_no, name, idx, 1)
                self._log(
                    f"[조건] SendCondition name={name} idx={idx} screen={screen_no} search_type=1 ret={ret}"
                )
                if ret != 1:
                    self._log(
                        f"[조건][ERROR] SendCondition 실패 name={name} idx={idx} screen={screen_no} ret={ret}"
                    )
            except Exception as exc:  # pragma: no cover - runtime dependent
                self._log(f"조건 실행 실패({name}): {exc}")

        self._log(f"[GROUP] expression configured: {self._group_preview_text()}")
        self._log("[GROUP] evaluation rule: expression-based (AND>OR precedence)")
        self._evaluate_universe(log_prefix="EVAL")

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
        if self.engine.broker_mode == "real" and not self.real_order_checkbox.isChecked():
            self._log("[주문] 실주문 비활성화 상태 → 테스트 실행 차단")
            return

        open_flag, reason, now = self._market_state()
        if self.enforce_market_hours and not open_flag:
            self._log_market_guard(reason, now)
            return

        if not self.condition_universe:
            self._log("[유니버스] 조건 결과가 없음(condition_universe empty) → 매매판단 스킵")
            diag = self._last_universe_diag or {}
            reason = diag.get("reason")
            message = diag.get("message", "")
            if not reason:
                reason, message = classify_universe_empty(diag)
            self._log(
                message
                or "[체크리스트] 조건 실행(실시간 포함) 버튼 실행 여부 / SendCondition ret=1 여부 / TR 조건결과 수신 로그를 확인하세요."
            )
            self._log(f"[유니버스][diag] {json.dumps(diag, ensure_ascii=False)}")
            return

        self.engine.set_external_universe(list(self.condition_universe))
        self._log(
            f"[AUTO] external_universe_count={len(self.condition_universe)} mode={self.engine.broker_mode}"
        )
        self._log(f"[유니버스] selector 사용 목록: external_universe 우선 적용 ({len(self.condition_universe)}건)")
        allow_orders = self.trading_orders_enabled or open_flag
        if not allow_orders:
            self._log("[자동매매] 주문 비활성 상태 → 평가만 수행 또는 스킵")
        self.engine.run_once("combined", allow_orders=allow_orders)
        self._refresh_account()
        self._refresh_positions(market_open=self._is_market_open())
        self._log(f"테스트 실행 1회 완료 ({len(self.strategy.positions)}개 보유)")

    def on_auto_start(self) -> None:
        if self.auto_timer.isActive():
            return

        server_info = "-"
        openapi = getattr(self.kiwoom_client, "openapi", None)
        if openapi:
            server_info = openapi.get_server_gubun_raw()
        self._log(
            f"[자동매매] 시작 버튼 클릭 - mode={self.engine.broker_mode} server_gubun={server_info}"
        )
        if self.engine.broker_mode == "real" and not self.real_order_checkbox.isChecked():
            self._log("[주문] 실주문 비활성화 상태 → 자동매수 시작 차단")
            return

        open_flag, reason, now = self._market_state()
        rt_counts = self.condition_manager.counts()
        active_conditions = [t.get("value") for t in self.builder_tokens if t.get("type") == "COND"]
        if active_conditions and all(v == 0 for v in rt_counts.values()):
            if not self._warned_no_cond_event and (
                not self._last_cond_event_ts or (time.time() - self._last_cond_event_ts) > 30
            ):
                self._log(
                    "[조건][WARN] 조건 결과를 아직 수신하지 못했습니다. '조건 실행(실시간 포함)'을 눌러 SendCondition 실행 후 [COND_EVT] 로그가 나오는지 확인하세요."
                )
                self._warned_no_cond_event = True
        self.auto_trading_active = True
        if open_flag:
            self.auto_trading_armed = False
            self.trading_orders_enabled = True
            self.status_label.setText("상태: 자동 매매 중 (주문 활성화)")
        else:
            self.auto_trading_armed = True
            self.trading_orders_enabled = not self.enforce_market_hours
            self.status_label.setText("상태: 감시중 (장전 대기)")
            self._log_market_guard(reason, now)

        self.auto_timer.start()
        self._log("자동 매매 시작 (타이머 가동)")

    def on_auto_stop(self) -> None:
        if self.auto_timer.isActive():
            self.auto_timer.stop()
            self.status_label.setText("상태: 매수 종료됨 (자동 정지)")
            self._log("자동 매매 정지")
        self.auto_trading_active = False
        self.auto_trading_armed = False
        self.trading_orders_enabled = False

    def _on_cycle(self) -> None:
        self._on_eod_check()
        if self.eod_executed_today == datetime.date.today():
            return
        open_flag, reason, now = self._market_state()
        allow_orders = True

        # 장 상태 변경 감지 (once per transition)
        if self._last_open_flag is None:
            self._last_open_flag = open_flag
        elif self._last_open_flag != open_flag:
            self._last_open_flag = open_flag
            if open_flag:
                self.trading_orders_enabled = True
                self.auto_trading_armed = False
                self._log("[상태] 장 시작 감지 → 주문 활성화(trading_orders_enabled=True)")
            else:
                if self.enforce_market_hours:
                    self.trading_orders_enabled = False
                self.auto_trading_armed = True
                self._log_market_guard(reason, now)

        if not open_flag:
            if not self.allow_premarket_monitor_checkbox.isChecked():
                self._log_market_guard(reason, now)
                self._refresh_positions(market_open=False)
                return
            self._log_market_guard(reason, now)
            if self.enforce_market_hours:
                allow_orders = False
            self._log(
                f"[장시간] 장전 감시 중: 조건 누적은 계속, 주문만 스킵(now={now.strftime('%Y-%m-%d %H:%M:%S')} range={self.market_start}-{self.market_end})"
            )
        if not self.condition_universe:
            self._log("[유니버스] 조건 결과가 없음(condition_universe empty) → 매매판단 스킵")
            diag = self._last_universe_diag or {}
            reason = diag.get("reason")
            message = diag.get("message", "")
            if not reason:
                reason, message = classify_universe_empty(diag)
            self._log(
                message
                or "[체크리스트] 조건 실행(실시간 포함) 버튼 실행 여부 / SendCondition ret=1 여부 / TR 조건결과 수신 로그를 확인하세요."
            )
            self._log(f"[유니버스][diag] {json.dumps(diag, ensure_ascii=False)}")
            self._refresh_positions(market_open=self._is_market_open())
            return
        self.engine.set_external_universe(list(self.condition_universe))
        if self.enforce_market_hours:
            allow_orders = self.trading_orders_enabled and open_flag
        else:
            allow_orders = self.trading_orders_enabled
        self._log(
            f"[AUTO] broker_mode={self.engine.broker_mode} open_flag={open_flag} enforce_market_hours={self.enforce_market_hours} allow_orders={allow_orders} universe={len(self.condition_universe)} holdings={len(self.strategy.positions)} max_positions={self.strategy.max_positions}"
        )
        self._log(f"[유니버스] selector 사용 목록: external_universe 우선 적용 ({len(self.condition_universe)}건)")
        if not allow_orders:
            self._log("[자동매매] 감시모드: 주문 차단 상태로 평가만 진행 또는 스킵")
        self.engine.run_once("combined", allow_orders=allow_orders)
        self._refresh_account()
        self._refresh_positions(market_open=self._is_market_open())

    def _market_state(self) -> tuple[bool, str, datetime.datetime]:
        now = datetime.datetime.now()
        weekday = now.strftime("%a")
        if now.weekday() >= 5:
            return False, f"주말/휴장 (weekday={weekday})", now
        now_time = now.time()
        if now_time < self.market_start:
            return False, (
                f"정규장 전 (now={now.strftime('%Y-%m-%d %H:%M:%S')} weekday={weekday} range={self.market_start}-{self.market_end})"
            ), now
        if now_time > self.market_end:
            return False, (
                f"정규장 종료 후 (now={now.strftime('%Y-%m-%d %H:%M:%S')} weekday={weekday} range={self.market_start}-{self.market_end})"
            ), now
        return True, (
            f"정규장 중 (now={now.strftime('%Y-%m-%d %H:%M:%S')} weekday={weekday} range={self.market_start}-{self.market_end})"
        ), now

    def _is_market_open(self) -> bool:
        open_flag, _, _ = self._market_state()
        return open_flag

    def _log_market_guard(self, reason: str, now: datetime.datetime) -> None:
        if self._last_market_reason != reason or not self._last_market_log:
            self._last_market_reason = reason
            self._last_market_log = now
            self._log(f"[장시간] {reason}")
            return
        if (now - self._last_market_log).total_seconds() >= 60:
            self._last_market_log = now
            self._log(f"[장시간] {reason} (지속)")

    def _restore_condition_choices(self, trigger_name: str, today_candidates: list[str]) -> None:
        self._pending_trigger_name = trigger_name or ""
        self._pending_today_candidates = today_candidates or []
        # trigger
        for i in range(self.trigger_combo.count()):
            data = self.trigger_combo.itemData(i)
            if data == self._pending_trigger_name:
                self.trigger_combo.setCurrentIndex(i)
                break
        # today candidates
        names = set(self._pending_today_candidates)
        for i in range(self.today_candidate_list.count()):
            item = self.today_candidate_list.item(i)
            data = item.data(Qt.UserRole)
            item.setCheckState(Qt.Checked if data in names else Qt.Unchecked)

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
            account_pw = self.account_pw_input.text().strip()
            if not account_pw:
                self._log(
                    "[실거래] 계좌비밀번호가 필요합니다. 입력 후 '잔고 새로고침'을 다시 눌러주세요."
                )
                return
            ok = openapi.request_deposit_and_holdings(account, account_pw=account_pw)
            if ok:
                masked = f"{account[:-2]}**" if len(account) > 2 else "**"
                self._log(f"[실거래] 잔고/보유종목 TR 요청(account={masked})")
            else:
                if getattr(openapi, "_balance_req_inflight", False):
                    self._log("[실거래] 잔고 조회 요청이 진행 중입니다. 잠시 후 다시 시도하세요.")
                else:
                    self._log(
                        "[실거래] 잔고 조회 요청이 실패했습니다. 비밀번호 입력 및 로그인 상태를 확인하세요."
                    )
        else:
            self._log("[실거래] 잔고 조회 불가: OpenAPI 컨트롤 없음 또는 미로그인")

    def _open_account_pw_window(self) -> None:
        """Manually open the Kiwoom password window to avoid (44) popups."""

        openapi = getattr(self.kiwoom_client, "openapi", None)
        if not (openapi and hasattr(openapi, "show_account_password_window")):
            self._log("[실거래] 계좌 비밀번호 창 호출 불가: OpenAPI 컨트롤이 없습니다.")
            return
        if openapi.show_account_password_window():
            self._log(
                "[실거래] 계좌비밀번호 입력창을 열었습니다. 입력/저장 후 '잔고 새로고침'을 다시 눌러주세요."
            )
        else:
            self._log(
                "[실거래] 계좌비밀번호 입력창 호출 실패 또는 이미 열려 있습니다. Kiwoom 트레이 상태를 확인하세요."
            )

    def _open_trade_history(self) -> None:
        dialog = TradeHistoryDialog(self.history_store, self)
        dialog.exec_()

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
        self.trigger_combo.clear()
        self.trigger_combo.addItem("(사용 안 함)", "")
        self.today_candidate_list.clear()
        self.condition_map.clear()
        self.all_conditions = [(int(idx), name) for idx, name in conditions]
        for idx, name in self.all_conditions:
            item = QListWidgetItem(f"{idx}: {name}")
            item.setData(Qt.UserRole, (idx, name))
            item.setCheckState(Qt.Unchecked)
            self.condition_list.addItem(item)
            self.condition_map[name] = (idx, name)
            self.trigger_combo.addItem(f"{idx}: {name}", name)
            cand_item = QListWidgetItem(f"{idx}: {name}")
            cand_item.setData(Qt.UserRole, name)
            cand_item.setCheckState(Qt.Unchecked)
            self.today_candidate_list.addItem(cand_item)

        if not self._pending_trigger_name:
            self._pending_trigger_name = str(self.settings.value("universe/trigger", "") or "")
        if not self._pending_today_candidates:
            raw_today = self.settings.value("universe/today_candidates", "") or ""
            self._pending_today_candidates = [x for x in str(raw_today).split(",") if x]
        self._restore_condition_choices(self._pending_trigger_name, self._pending_today_candidates)

        valid_names = {name for _, name in self.all_conditions}
        pruned = False
        new_tokens: list[dict] = []
        for token in self.builder_tokens:
            if token.get("type") == "COND" and token.get("value") not in valid_names:
                pruned = True
                self._log(f"[GROUP] 조건식이 더 이상 존재하지 않아 토큰에서 제거: {token.get('value')}")
                continue
            new_tokens.append(token)
        if pruned:
            self.builder_tokens = new_tokens
            self._refresh_builder_strip()
        try:
            self._update_expression_from_tokens(reset_sets=True)
        except Exception as exc:  # noqa: BLE001
            self._log(f"[ERR] refresh_condition_list update failed: {exc}")
            logger.exception("Failed to refresh condition expression after reload")
        if self._pending_preset_state:
            self._apply_preset_state(self._pending_preset_state, name=self._pending_preset_name)
            self._pending_preset_state = None

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
