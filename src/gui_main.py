"""PyQt5 GUI for the Mystock02 auto-trading playground."""

import datetime
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Callable, List, Optional, Sequence

try:
    from PyQt5.QtCore import Qt, QTimer, pyqtSlot, QSettings
    from PyQt5.QtGui import QFontMetrics
    from PyQt5.QtWidgets import (
        QApplication,
        QAbstractScrollArea,
        QButtonGroup,
        QCheckBox,
        QComboBox,
        QDialog,
        QDialogButtonBox,
        QDoubleSpinBox,
        QFileDialog,
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
        QScrollArea,
        QSizePolicy,
        QTabWidget,
        QSplitter,
        QSpinBox,
        QTableWidget,
        QTableWidgetItem,
        QPlainTextEdit,
        QTextEdit,
        QTimeEdit,
        QVBoxLayout,
        QWidget,
    )
except ImportError as exc:  # pragma: no cover - environment may lack PyQt5
    raise SystemExit("PyQt5 is required to run the GUI. Install it with 'pip install pyqt5'.") from exc

if sys.version_info < (3, 8):  # pragma: no cover - defensive guard for old installs
    raise SystemExit("Python 3.8+ is required to run the GUI. Please upgrade your interpreter.")

from .app_paths import (
    ensure_data_dirs,
    monitor_snapshot_path,
    reports_dir,
    resolve_data_dir,
    settings_ini_path,
)
from .config import AppConfig, load_config
from .condition_manager import ConditionManager
from .kiwoom_client import KiwoomClient
from .kiwoom_openapi import KiwoomOpenAPI, QAX_AVAILABLE
from .paper_broker import PaperBroker
from .opportunity_tracker import MissedOpportunityTracker
from .scanner import ScannerConfig, ScannerEngine
from .selector import UniverseSelector
from .strategy import Strategy, Order
from .trade_engine import TradeEngine
from .trade_history_store import TradeHistoryStore
from .universe_diag import classify_universe_empty
from .gui_trade_history import TradeHistoryDialog
from .logging_setup import configure_logging
from .backup_manager import BackupManager
from .gui_restore_wizard import RestoreWizard
from .gui_reports import ReportsWidget
from .buy_decision_logger import BuyDecisionLogger
from .persistence import load_json, save_json

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

        self.secure_settings = QSettings("Mystock02", "AutoTrader")

        user_dir = self.secure_settings.value("storage/data_dir", "")
        self.data_dir = resolve_data_dir(user_dir)
        ensure_data_dirs(self.data_dir)

        self.settings = QSettings(str(settings_ini_path(self.data_dir)), QSettings.IniFormat)
        self.settings.setFallbacksEnabled(False)

        if not settings_ini_path(self.data_dir).exists() or len(self.settings.allKeys()) == 0:
            try:
                allow_prefixes = ("ui/", "strategy/", "universe/", "builder/", "test/")
                for key in self.secure_settings.allKeys():
                    if key.startswith(allow_prefixes):
                        self.settings.setValue(key, self.secure_settings.value(key))
                self.settings.sync()
                logger.info("[MIGRATE] legacy registry settings -> ini done")
            except Exception as exc:
                logger.info("[MIGRATE] skipped: %s", exc)

        backup_mode = str(self.settings.value("backup/mode", "zip"))
        self.backup = BackupManager(
            self.data_dir, keep_last=int(self.settings.value("backup/keep_last", 30)), mode=backup_mode
        )
        self.last_backup_label_text = ""
        self._backup_last_payload: dict = {}
        logger.info(
            "[PERSIST] data_dir=%s settings_ini=%s",
            self.data_dir,
            settings_ini_path(self.data_dir),
        )

        self.history_store = TradeHistoryStore()
        self.current_config = load_config()
        self.strategy = Strategy()
        self.kiwoom_client = KiwoomClient(
            account_no=self.secure_settings.value("connection/real/account_no", self.current_config.account_no),
            app_key=self.secure_settings.value("connection/real/app_key", self.current_config.app_key),
            app_secret=self.secure_settings.value("connection/real/app_secret", self.current_config.app_secret),
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
        paper_broker = PaperBroker(
            initial_cash=self.strategy.initial_cash,
            history_store=self.history_store,
            name_resolver=self._get_symbol_name,
        )
        self.engine = TradeEngine(
            strategy=self.strategy,
            selector=self.selector,
            broker_mode="paper",
            kiwoom_client=self.kiwoom_client,
            paper_broker=paper_broker,
            log_fn=self._log,
        )
        self.engine.set_buy_limits(rebuy_after_sell_today=False, max_buy_per_symbol_today=1)
        self.buy_decision_logger = BuyDecisionLogger(self.data_dir / "opportunity" / "buy_decisions.csv")
        self.engine.set_decision_logger(self.buy_decision_logger)
        self.condition_map = {}
        self.condition_screens: dict[str, str] = {}
        self.condition_manager = ConditionManager()
        self.builder_tokens: list[dict] = []
        self.condition_universe: set[str] = set()
        self.condition_universe_today: set[str] = set()
        self._last_send_condition_ret: int | None = None
        self._last_selected_condition_name: str | None = None
        self._last_selected_condition_idx: int | None = None
        self._last_tr_condition_ts: float | None = None
        self._last_real_condition_ts: float | None = None
        self._monitor_last_update: dict[str, str] = {}
        self._monitor_events: list[dict] = []
        self.monitor_snapshot_path = monitor_snapshot_path(self.data_dir)
        self._persist_monitor_timer = QTimer(self)
        self._persist_monitor_timer.setSingleShot(True)
        self._persist_monitor_timer.timeout.connect(self._save_monitor_snapshot)
        self._universe_refresh_scheduled: bool = False
        self.universe_mode: str = "condition"
        self.test_universe: set[str] = set()
        self.enforce_market_hours: bool = True
        self.market_start = datetime.time(9, 0)
        self.market_end = datetime.time(15, 20)
        self.auto_trading_active: bool = False
        self.auto_trading_armed: bool = False
        self.trading_orders_enabled: bool = False
        self._auto_condition_bootstrap_done: bool = False
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
        self._engine_busy: bool = False
        self._status_before_busy: Optional[str] = None
        self._scanner_busy: bool = False
        self.scanner_current_universe: list[str] = []
        self.scanner_config = ScannerConfig()
        self.scanner = ScannerEngine(self.selector.score_candidates, config=self.scanner_config)
        self.opportunity_tracker = MissedOpportunityTracker(self.data_dir / "opportunity")
        self._last_scan_result = None
        self._scanner_next_run_at: Optional[datetime.datetime] = None
        self.last_scanner_attempt_ts: Optional[datetime.datetime] = None
        self.last_scanner_ok_ts: Optional[datetime.datetime] = None
        self.last_scanner_trigger: str = ""
        self.last_scanner_source: str = ""
        self.last_scanner_tr_meta: dict = {}
        self._last_realreg_set: set[str] = set()
        self._last_realreg_ts: float = 0.0
        self.realreg_limit = 100
        self._no_buy_history: list[dict] = []

        self.auto_timer = QTimer(self)
        self.auto_timer.timeout.connect(self._on_cycle)
        self.auto_timer.setInterval(5000)

        self.scanner_timer = QTimer(self)
        self.scanner_timer.timeout.connect(self._on_scanner_cycle)
        self.scanner_timer.setInterval(60_000)
        self.scan_countdown_timer = QTimer(self)
        self.scan_countdown_timer.timeout.connect(self._update_scan_schedule_ui)
        self.scan_countdown_timer.setInterval(1000)
        self.scan_countdown_timer.start()

        self.backup_enabled = bool(int(self.settings.value("backup/enabled", 1)))
        self.backup_interval_min = int(self.settings.value("backup/interval_min", 10))
        self._backup_timer = QTimer(self)
        self._backup_timer.timeout.connect(self._run_auto_backup)
        if self.backup_enabled:
            self._backup_timer.start(self.backup_interval_min * 60 * 1000)

        self.close_timer = QTimer(self)
        self.close_timer.timeout.connect(self._on_eod_check)
        self.close_timer.setInterval(30_000)
        self.close_timer.start()
        self.eod_executed_today: Optional[datetime.date] = None

        self._build_layout()
        self._load_backup_status()
        self._update_backup_status_labels()
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
        self._maybe_restore_paper_from_db(trigger="startup")
        self._apply_mode_enable()
        self._refresh_condition_list()
        self._refresh_account()
        self._refresh_positions()
        self._update_connection_labels()
        self._load_monitor_snapshot()

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

        self.condition_list = QListWidget()
        self.condition_list.setSelectionMode(QListWidget.MultiSelection)
        self.condition_list.setMinimumWidth(240)
        self.condition_list.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
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
        self.auto_run_condition_on_start_checkbox = QCheckBox("자동매매 시작 시 조건 자동실행(SendCondition)")
        self.auto_run_condition_on_start_checkbox.setChecked(True)
        self.auto_run_condition_on_start_checkbox.setToolTip(
            "조건 조인/조건모드 사용 시 자동매매 시작만 눌러도 조건 실행을 자동 시도합니다. 실패 시 로그로 원인 확인 가능"
        )

        left_panel = QVBoxLayout()
        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("유니버스 모드"))
        self.universe_mode_combo = QComboBox()
        self.universe_mode_combo.addItem("조건검색 모드", "condition")
        self.universe_mode_combo.addItem("스캐너 모드", "scanner")
        self.universe_mode_combo.addItem("테스트 모드", "test")
        mode_row.addWidget(self.universe_mode_combo)
        left_panel.addLayout(mode_row)
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
        gate_layout.addRow(self.auto_run_condition_on_start_checkbox)
        left_panel.addLayout(gate_layout)

        self.test_group = QGroupBox("테스트 유니버스")
        test_layout = QVBoxLayout()
        input_row = QHBoxLayout()
        self.test_symbol_input = QLineEdit()
        self.test_symbol_input.setPlaceholderText("005930 또는 005930,000660")
        self.test_add_btn = QPushButton("추가")
        self.test_add_bulk_btn = QPushButton("일괄 추가")
        input_row.addWidget(self.test_symbol_input)
        input_row.addWidget(self.test_add_btn)
        input_row.addWidget(self.test_add_bulk_btn)
        test_layout.addLayout(input_row)
        self.test_universe_list = QListWidget()
        test_layout.addWidget(self.test_universe_list)
        action_row = QHBoxLayout()
        self.test_remove_btn = QPushButton("삭제")
        self.test_clear_btn = QPushButton("전체삭제")
        action_row.addWidget(self.test_remove_btn)
        action_row.addWidget(self.test_clear_btn)
        test_layout.addLayout(action_row)
        self.test_dry_run_checkbox = QCheckBox("DRY_RUN (실주문 전송 안 함)")
        self.test_dry_run_checkbox.setChecked(True)
        test_layout.addWidget(self.test_dry_run_checkbox)
        force_row = QHBoxLayout()
        self.test_force_buy_btn = QPushButton("강제 매수(테스트)")
        self.test_force_sell_btn = QPushButton("강제 매도(테스트)")
        force_row.addWidget(self.test_force_buy_btn)
        force_row.addWidget(self.test_force_sell_btn)
        test_layout.addLayout(force_row)
        self.test_group.setLayout(test_layout)
        left_panel.addWidget(self.test_group)

        self.scanner_health_group = QGroupBox("스캐너/매수 헬스체크")
        scanner_health_layout = QVBoxLayout()
        source_row = QHBoxLayout()
        self.scanner_source_combo = QComboBox()
        self.scanner_source_combo.addItem("조건 결과", "condition")
        self.scanner_source_combo.addItem("거래대금 상위(OPT10030)", "opt10030_trade_value")
        self.scanner_source_combo.addItem("등락률 상위(OPT10027)", "opt10027_change_rate")
        self.scanner_market_combo = QComboBox()
        self.scanner_market_combo.addItem("전체(000)", "000")
        self.scanner_market_combo.addItem("코스피(001)", "001")
        self.scanner_market_combo.addItem("코스닥(101)", "101")
        source_idx = self.scanner_source_combo.findData(self.scanner_config.candidate_source)
        if source_idx >= 0:
            self.scanner_source_combo.setCurrentIndex(source_idx)
        market_idx = self.scanner_market_combo.findData(self.scanner_config.market_code)
        if market_idx >= 0:
            self.scanner_market_combo.setCurrentIndex(market_idx)
        source_row.addWidget(QLabel("후보 소스"))
        source_row.addWidget(self.scanner_source_combo)
        source_row.addWidget(QLabel("시장"))
        source_row.addWidget(self.scanner_market_combo)
        scanner_health_layout.addLayout(source_row)
        self.scan_once_btn = QPushButton("지금 스캔 1회")
        self.scan_once_btn.setObjectName("btn_scan_once")
        self.scan_next_label = QLabel("다음 스캔: -")
        self.scan_countdown_label = QLabel("남은 시간: -")
        self.scanner_status_label = QLabel("마지막 스캔: -")
        self.scanner_health_btn = QPushButton("스캐너/매수 헬스체크")
        self.scanner_health_text = QPlainTextEdit()
        self.scanner_health_text.setReadOnly(True)
        self.scanner_health_text.setPlaceholderText("헬스체크 결과가 여기에 표시됩니다.")
        self.scanner_health_text.setMinimumHeight(160)
        scanner_health_layout.addWidget(self.scan_once_btn)
        scanner_health_layout.addWidget(self.scan_next_label)
        scanner_health_layout.addWidget(self.scan_countdown_label)
        scanner_health_layout.addWidget(self.scanner_status_label)
        scanner_health_layout.addWidget(self.scanner_health_btn)
        scanner_health_layout.addWidget(self.scanner_health_text)
        self.scanner_health_group.setLayout(scanner_health_layout)
        left_panel.addWidget(self.scanner_health_group)

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

        cond_splitter = QSplitter(Qt.Horizontal)
        left_widget = QWidget()
        left_widget.setLayout(left_panel)
        right_widget = QWidget()
        right_widget.setLayout(right_panel)
        cond_splitter.addWidget(left_widget)
        cond_splitter.addWidget(right_widget)
        cond_layout = QVBoxLayout()
        cond_layout.addWidget(cond_splitter)
        cond_group.setLayout(cond_layout)

        # Condition realtime monitor (0156)
        monitor_group = QGroupBox("조건 실시간 모니터 (0156)")
        monitor_layout = QVBoxLayout()
        monitor_controls = QHBoxLayout()
        self.monitor_condition_combo = QComboBox()
        self.monitor_condition_combo.addItem("전체", "")
        self.monitor_condition_combo.addItem("조인결과(최종 유니버스)", "__JOINED__")
        self.monitor_condition_combo.setCurrentIndex(1)
        self.monitor_refresh_btn = QPushButton("현재결과 새로고침")
        self.monitor_reset_btn = QPushButton("이벤트 초기화")
        self.monitor_export_btn = QPushButton("CSV 내보내기")
        self.no_buy_reason_btn = QPushButton("미매수 사유")
        self.monitor_status_label = QLabel(
            "조건 실행(실시간 포함)을 누르면 현재결과/편입/편출 이벤트가 표시됩니다."
        )
        monitor_controls.addWidget(QLabel("조건"))
        monitor_controls.addWidget(self.monitor_condition_combo)
        monitor_controls.addWidget(self.monitor_refresh_btn)
        monitor_controls.addWidget(self.monitor_reset_btn)
        monitor_controls.addWidget(self.monitor_export_btn)
        monitor_controls.addWidget(self.no_buy_reason_btn)
        monitor_controls.addWidget(self.monitor_status_label)
        monitor_layout.addLayout(monitor_controls)

        splitter = QSplitter(Qt.Horizontal)
        self.monitor_result_table = QTableWidget(0, 4)
        self.monitor_result_table.setHorizontalHeaderLabels(["코드", "종목명", "마지막갱신", "상태"])
        self.monitor_result_table.horizontalHeader().setStretchLastSection(True)
        self.monitor_event_table = QTableWidget(0, 6)
        self.monitor_event_table.setHorizontalHeaderLabels(
            ["시각", "이벤트", "조건명", "코드", "종목명", "비고"]
        )
        self.monitor_event_table.horizontalHeader().setStretchLastSection(True)
        splitter.addWidget(self.monitor_result_table)
        splitter.addWidget(self.monitor_event_table)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)
        monitor_layout.addWidget(splitter)
        monitor_group.setLayout(monitor_layout)

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

        self._engine_action_buttons = [
            self.test_force_buy_btn,
            self.test_force_sell_btn,
            self.test_btn,
            self.auto_start_btn,
            self.auto_stop_btn,
            self.apply_btn,
        ]

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
        # Positions and log
        self.positions_table = QTableWidget(0, 6)
        self.positions_table.setHorizontalHeaderLabels(["종목코드", "종목명", "수량", "진입가", "최고가", "현재가/등락"])

        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)

        self.main_tabs = QTabWidget()

        def wrap_tab(widget: QWidget) -> QScrollArea:
            area = QScrollArea()
            area.setWidgetResizable(True)
            area.setWidget(widget)
            return area

        tab_condition = QWidget()
        tab_condition_layout = QVBoxLayout()
        tab_condition_layout.addWidget(conn_group)
        tab_condition_layout.addWidget(cond_group)
        tab_condition_layout.addStretch(1)
        tab_condition.setLayout(tab_condition_layout)
        self.main_tabs.addTab(wrap_tab(tab_condition), "조건/유니버스")

        tab_monitor = QWidget()
        tab_monitor_layout = QVBoxLayout()
        tab_monitor_layout.addWidget(monitor_group)
        tab_monitor_layout.addStretch(1)
        tab_monitor.setLayout(tab_monitor_layout)
        self.main_tabs.addTab(wrap_tab(tab_monitor), "모니터")

        tab_strategy = QWidget()
        tab_strategy_layout = QVBoxLayout()
        tab_strategy_layout.addWidget(param_group)
        tab_strategy_layout.addWidget(self.positions_table)
        tab_strategy_layout.addStretch(1)
        tab_strategy.setLayout(tab_strategy_layout)
        self.main_tabs.addTab(wrap_tab(tab_strategy), "전략/포지션")

        tab_log = QWidget()
        tab_log_layout = QVBoxLayout()

        top_wrap = QVBoxLayout()

        info_row = QHBoxLayout()
        self.data_dir_label = QLabel("DATA: -")
        self.backup_status_label = QLabel("BACKUP: (unknown)")
        self.last_backup_label = QLabel("LAST: (none)")
        self.backup_count_label = QLabel("FILES: 0")
        self.backup_path_label = QLabel("PATH: -")
        self.backup_err_label = QLabel("")

        for lb in (self.data_dir_label, self.backup_path_label):
            lb.setToolTip("")
            lb.setMinimumWidth(200)
            lb.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        info_row.addWidget(self.data_dir_label, 3)
        info_row.addWidget(self.backup_status_label)
        info_row.addWidget(self.last_backup_label)
        info_row.addWidget(self.backup_count_label)
        info_row.addWidget(self.backup_path_label, 2)
        info_row.addWidget(self.backup_err_label, 2)
        top_wrap.addLayout(info_row)

        btn_row = QHBoxLayout()
        self.open_data_dir_btn = QPushButton("폴더 열기")
        self.change_data_dir_btn = QPushButton("데이터 경로 변경")
        self.backup_now_btn = QPushButton("지금 백업")
        self.restore_wizard_btn = QPushButton("복원 마법사")

        btn_row.addWidget(self.open_data_dir_btn)
        btn_row.addWidget(self.change_data_dir_btn)
        btn_row.addStretch(1)
        btn_row.addWidget(self.backup_now_btn)
        btn_row.addWidget(self.restore_wizard_btn)
        top_wrap.addLayout(btn_row)

        tab_log_layout.addLayout(top_wrap)
        tab_log_layout.addWidget(self.log_view)
        tab_log.setLayout(tab_log_layout)
        self.main_tabs.addTab(wrap_tab(tab_log), "로그")

        report_widget = ReportsWidget(
            self.history_store,
            reports_dir=reports_dir(self.data_dir),
            parent=self,
            name_resolver=self._get_symbol_name,
        )
        self.main_tabs.addTab(wrap_tab(report_widget), "리포트")

        main.addWidget(self.main_tabs)
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
        self.open_data_dir_btn.clicked.connect(self._open_data_dir)
        self.change_data_dir_btn.clicked.connect(self._change_data_dir)
        self.backup_now_btn.clicked.connect(lambda: self._run_backup_ui("manual"))
        self.restore_wizard_btn.clicked.connect(self._open_restore_wizard)
        self.refresh_conditions_btn.clicked.connect(self._refresh_condition_list)
        self.run_condition_btn.clicked.connect(self._execute_condition)
        self.preview_candidates_btn.clicked.connect(self._preview_candidates)
        self.add_selected_btn.clicked.connect(self._on_add_selected_conditions)
        self.wrap_btn.clicked.connect(self._wrap_selection)
        self.validate_btn.clicked.connect(self._validate_builder)
        self.clear_builder_btn.clicked.connect(self._clear_builder)
        self.monitor_refresh_btn.clicked.connect(self._refresh_monitor_results)
        self.monitor_reset_btn.clicked.connect(self._reset_monitor_events)
        self.monitor_export_btn.clicked.connect(self._export_monitor_csv)
        self.no_buy_reason_btn.clicked.connect(self._open_no_buy_history)
        self.monitor_condition_combo.currentIndexChanged.connect(self._refresh_monitor_results)
        self.universe_mode_combo.currentIndexChanged.connect(self._on_universe_mode_changed)
        self.test_add_btn.clicked.connect(self._add_test_symbols)
        self.test_add_bulk_btn.clicked.connect(self._add_test_symbols_bulk)
        self.test_remove_btn.clicked.connect(self._remove_test_symbol)
        self.test_clear_btn.clicked.connect(self._clear_test_symbols)
        self.test_force_buy_btn.clicked.connect(self._force_test_buy)
        self.test_force_sell_btn.clicked.connect(self._force_test_sell)
        self.scanner_health_btn.clicked.connect(self._run_scanner_healthcheck)
        self.scan_once_btn.clicked.connect(self._on_scan_once_clicked)
        logger.info("[SCANNER_UI] scan_once_button_connected=True")
        self.scanner_source_combo.currentIndexChanged.connect(self._on_scanner_source_changed)
        self.scanner_market_combo.currentIndexChanged.connect(self._on_scanner_market_changed)
        self.preset_save_btn.clicked.connect(self._on_save_preset)
        self.preset_load_btn.clicked.connect(self._on_load_preset)
        self.preset_delete_btn.clicked.connect(self._on_delete_preset)
        self.trigger_combo.currentIndexChanged.connect(self._save_current_settings)
        self.today_candidate_list.itemChanged.connect(lambda *_: self._save_current_settings())
        self.gate_after_trigger_checkbox.toggled.connect(self._save_current_settings)
        self.allow_premarket_monitor_checkbox.toggled.connect(self._save_current_settings)
        self.auto_run_condition_on_start_checkbox.toggled.connect(self._save_current_settings)
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
        if self.openapi_widget and hasattr(self.openapi_widget, "condition_raw_log"):
            self.openapi_widget.condition_raw_log.connect(self._on_condition_raw_log)

    # Settings ---------------------------------------------------------
    def _settings_mode(self) -> str:
        return "paper" if self.paper_radio.isChecked() else "real"

    def _paper_restore_enabled(self) -> bool:
        return bool(int(self.settings.value("paper_restore/enabled", 1)))

    def _paper_restore_range(self) -> tuple[str, str]:
        now = datetime.datetime.now()
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        return start.strftime("%Y-%m-%d %H:%M:%S"), now.strftime("%Y-%m-%d %H:%M:%S")

    def _maybe_restore_paper_from_db(self, trigger: str = "manual") -> None:
        try:
            if self.engine.broker_mode != "paper":
                return
            if not self._paper_restore_enabled():
                self._log(f"[PAPER_RESTORE] disabled (trigger={trigger})")
                return

            db_path = self.data_dir / "trade" / "trade_history.db"
            if not db_path.exists():
                self._log(f"[PAPER_RESTORE] db not found: {db_path}")
                return

            start_ts, end_ts = self._paper_restore_range()
            fallback_cash = float(self.paper_cash_input.value())

            self._log(
                f"[PAPER_RESTORE] start trigger={trigger} range={start_ts}~{end_ts} fallback_cash={fallback_cash}"
            )
            payload = self.engine.restore_paper_state_from_history(
                self.history_store,
                start_ts=start_ts,
                end_ts=end_ts,
                fallback_cash=fallback_cash,
            )
            self._log(
                f"[PAPER_RESTORE] end trigger={trigger} ok={payload.get('ok')} positions={len(payload.get('positions', {}))} cash={payload.get('cash')}"
            )
            if payload.get("warnings"):
                self._log(f"[PAPER_RESTORE] warnings={payload['warnings'][:5]}")

            self._refresh_account_and_positions()
        except Exception as exc:
            self._log(f"[PAPER_RESTORE][ERR] {exc}")

    def _load_settings(self) -> None:
        mode = self.settings.value("ui/mode", "paper")
        self._saved_mode = str(mode)
        if self._saved_mode == "real":
            self.real_radio.setChecked(True)
        else:
            self.paper_radio.setChecked(True)
        self._load_strategy_settings()
        self._load_universe_settings()
        self._load_test_universe()
        self._apply_universe_mode()
        self._apply_mode_enable()
        self._restore_window_state()
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
        auto_run = self.settings.value(prefix + "auto_run_condition_on_start", True, type=bool)
        rebuy = self.settings.value(prefix + "rebuy_after_sell", False, type=bool)
        max_buy = self.settings.value(prefix + "max_buy_per_symbol_today", 1)
        try:
            max_buy = int(max_buy)
        except Exception:
            max_buy = 1
        self.gate_after_trigger_checkbox.setChecked(bool(gate))
        self.allow_premarket_monitor_checkbox.setChecked(bool(premarket))
        self.auto_run_condition_on_start_checkbox.setChecked(bool(auto_run))
        self.rebuy_after_sell_checkbox.setChecked(bool(rebuy))
        self.max_buy_per_symbol_spin.setValue(max_buy)
        self._restore_condition_choices(trigger, today_candidates)
        self._on_buy_limit_changed()

    def _save_current_settings(self) -> None:
        mode = self._settings_mode()
        prefix = f"strategy/{mode}/"
        self.settings.setValue("ui/mode", mode)
        self.settings.setValue("ui/universe_mode", self.universe_mode)
        self.settings.setValue(prefix + "stop_loss_pct", self.stop_loss_input.value())
        self.settings.setValue(prefix + "take_profit_pct", self.take_profit_input.value())
        self.settings.setValue(prefix + "trailing_pct", self.trailing_input.value())
        self.settings.setValue(prefix + "paper_cash", self.paper_cash_input.value())
        self.settings.setValue(prefix + "max_positions", self.max_pos_input.value())
        self.settings.setValue(prefix + "buy_order_mode", self.buy_order_mode_combo.currentData())
        self.settings.setValue(prefix + "buy_offset_ticks", self.buy_price_offset_ticks.value())
        self.settings.setValue(prefix + "eod_time", self.eod_time_edit.time().toString("HH:mm"))
        if mode == "real":
            self.secure_settings.setValue("connection/real/account_no", self.account_combo.currentText())
            self.secure_settings.sync()
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
        self.settings.setValue(
            uni_prefix + "auto_run_condition_on_start",
            self.auto_run_condition_on_start_checkbox.isChecked(),
        )
        self.settings.setValue(uni_prefix + "rebuy_after_sell", self.rebuy_after_sell_checkbox.isChecked())
        self.settings.setValue(uni_prefix + "max_buy_per_symbol_today", self.max_buy_per_symbol_spin.value())
        self.settings.setValue("test/universe", ",".join(sorted(self.test_universe)))
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

    def _restore_window_state(self) -> None:
        geometry = self.settings.value("ui/window_geometry")
        if geometry:
            self.restoreGeometry(geometry)
        else:
            screen = QApplication.primaryScreen()
            if screen:
                rect = screen.availableGeometry()
                self.resize(int(rect.width() * 0.9), int(rect.height() * 0.85))
        tab_index = self.settings.value("ui/main_tab_index")
        if tab_index is not None and hasattr(self, "main_tabs"):
            try:
                self.main_tabs.setCurrentIndex(int(tab_index))
            except Exception:
                pass

    def _load_test_universe(self) -> None:
        raw = self.settings.value("test/universe", "") or ""
        self.test_universe = {s.strip() for s in str(raw).split(",") if s.strip()}
        self._refresh_test_list()
        saved_mode = self.settings.value("ui/universe_mode", "condition")
        idx = self.universe_mode_combo.findData(saved_mode)
        if idx >= 0:
            self.universe_mode_combo.setCurrentIndex(idx)

    def _apply_universe_mode(self) -> None:
        mode = self.universe_mode_combo.currentData() or "condition"
        self.universe_mode = str(mode)
        self._log(f"[MODE] universe_mode={self.universe_mode}")
        is_test = self.universe_mode == "test"
        is_scanner = self.universe_mode == "scanner"
        for widget in (
            self.refresh_conditions_btn,
            self.run_condition_btn,
            self.preview_candidates_btn,
            self.add_selected_btn,
            self.wrap_btn,
            self.validate_btn,
            self.clear_builder_btn,
        ):
            widget.setEnabled(not is_test)
        self.test_group.setEnabled(is_test)
        if is_test:
            self.engine.set_external_universe(list(self.test_universe))
        if is_scanner and self.auto_timer.isActive() and not self.scanner_timer.isActive():
            self.scanner_timer.start()
            self._scanner_next_run_at = datetime.datetime.now() + datetime.timedelta(
                seconds=self.scanner_timer.interval() / 1000
            )
            self._update_scan_schedule_ui()
            self._log("스캐너 모드 스캔 타이머 시작")
        if not is_scanner and self.scanner_timer.isActive():
            self.scanner_timer.stop()
            self._scanner_next_run_at = None
            self._update_scan_schedule_ui()
            self._log("스캐너 모드 스캔 타이머 중지")
        self._save_current_settings()

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

    def _on_universe_mode_changed(self) -> None:
        self._apply_universe_mode()

    def _normalize_symbol(self, text: str) -> str:
        text = text.strip().replace("A", "")
        return text

    def _refresh_test_list(self) -> None:
        self.test_universe_list.clear()
        for symbol in sorted(self.test_universe):
            self.test_universe_list.addItem(symbol)

    def _add_test_symbols(self) -> None:
        raw = self.test_symbol_input.text().strip()
        if not raw:
            return
        symbol = self._normalize_symbol(raw.split(",")[0])
        if symbol:
            self.test_universe.add(symbol)
            self._log(f"[TEST_UNIVERSE] add {symbol}")
        self.test_symbol_input.clear()
        self._refresh_test_list()
        self._save_current_settings()

    def _add_test_symbols_bulk(self) -> None:
        raw = self.test_symbol_input.text().strip()
        if not raw:
            return
        parts = [self._normalize_symbol(p) for p in raw.replace("\n", ",").split(",")]
        added = [p for p in parts if p]
        for symbol in added:
            self.test_universe.add(symbol)
        if added:
            self._log(f"[TEST_UNIVERSE] add_bulk {added}")
        self.test_symbol_input.clear()
        self._refresh_test_list()
        self._save_current_settings()

    def _remove_test_symbol(self) -> None:
        item = self.test_universe_list.currentItem()
        if not item:
            return
        symbol = item.text().strip()
        if symbol in self.test_universe:
            self.test_universe.remove(symbol)
            self._log(f"[TEST_UNIVERSE] remove {symbol}")
        self._refresh_test_list()
        self._save_current_settings()

    def _clear_test_symbols(self) -> None:
        self.test_universe.clear()
        self._log("[TEST_UNIVERSE] cleared")
        self._refresh_test_list()
        self._save_current_settings()

    def _force_test_buy(self) -> None:
        if self.universe_mode != "test":
            self._log("[TEST_FORCE_BUY] 테스트 모드에서만 실행됩니다.")
            return
        item = self.test_universe_list.currentItem()
        if not item:
            self._log("[TEST_FORCE_BUY] 종목을 선택하세요.")
            return

        symbol = item.text().strip()

        def run() -> None:
            price = self.engine.get_current_price(symbol)
            order = Order(side="buy", symbol=symbol, quantity=1, price=price)
            dry_run = self.test_dry_run_checkbox.isChecked()
            self._log(
                f"[TEST_FORCE_BUY] symbol={symbol} price={price:.2f} qty=1 dry_run={dry_run}"
            )
            self.engine._execute_orders([order], allow_orders=not dry_run)
            self._refresh_account_and_positions()
            QTimer.singleShot(200, self._refresh_account_and_positions)

        self._run_engine_task("TEST_FORCE_BUY", run)

    def _force_test_sell(self) -> None:
        if self.universe_mode != "test":
            self._log("[TEST_FORCE_SELL] 테스트 모드에서만 실행됩니다.")
            return
        item = self.test_universe_list.currentItem()
        if not item:
            self._log("[TEST_FORCE_SELL] 종목을 선택하세요.")
            return
        symbol = item.text().strip()
        pos = self.strategy.positions.get(symbol)
        if not pos:
            self._log(f"[TEST_FORCE_SELL] 보유 중인 종목이 아닙니다: {symbol}")
            return

        def run() -> None:
            price = self.engine.get_current_price(symbol)
            order = Order(side="sell", symbol=symbol, quantity=pos.quantity, price=price)
            dry_run = self.test_dry_run_checkbox.isChecked()
            self._log(
                f"[TEST_FORCE_SELL] symbol={symbol} price={price:.2f} qty={pos.quantity} dry_run={dry_run}"
            )
            self.engine._execute_orders([order], allow_orders=not dry_run)
            self._refresh_account_and_positions()
            QTimer.singleShot(200, self._refresh_account_and_positions)

        self._run_engine_task("TEST_FORCE_SELL", run)

    def _on_buy_order_mode_changed(self) -> None:
        mode = self.buy_order_mode_combo.currentData()
        offset = self.buy_price_offset_ticks.value()
        self.buy_price_offset_ticks.setEnabled(mode == "limit")
        self.engine.set_buy_pricing(mode, offset)
        self._save_current_settings()

    def on_open_config(self) -> None:
        dialog = ConfigDialog(self, self.current_config, self.kiwoom_client, self.secure_settings, self._settings_mode())
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
        name_key = self._canonical_condition_name(condition_name, index)
        self.condition_manager.update_condition(name_key, codes)
        label = self._condition_id_text(name_key)
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for code in codes:
            self._monitor_last_update[code] = now_str
        self._log(
            f"[COND_EVT] 초기 조회 결과 수신 cond={name_key}({label}) idx={index} count={len(codes)}"
        )
        self._last_cond_event_ts = time.time()
        self._last_tr_condition_ts = time.time()
        self._warned_no_cond_event = False
        note = f"TR {len(codes)}개"
        head = ", ".join(codes[:5])
        if head:
            note = f"{note} head={head}"
        self._add_monitor_event("TR", name_key, "", note=note)
        self._schedule_universe_refresh()

    @pyqtSlot(str, str, str, str)
    def _on_real_condition_received(self, code: str, event: str, condition_name: str, condition_index: str) -> None:
        name_key = self._canonical_condition_name(condition_name, condition_index)
        if not name_key:
            return
        self.condition_manager.apply_event(name_key, code, event)
        action = "편입" if event == "I" else "편출" if event == "D" else f"기타({event})"
        label = self._condition_id_text(name_key)
        self._monitor_last_update[code] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self._log(
            f"[COND_EVT] {action}: {code} (조건 {name_key}/{label}/{condition_index})"
        )
        self._last_cond_event_ts = time.time()
        self._last_real_condition_ts = time.time()
        self._warned_no_cond_event = False
        self._add_monitor_event(event, name_key, code, note=label)
        self._schedule_universe_refresh()

    def _recompute_universe(self) -> None:
        final_set = self._evaluate_universe(log_prefix="EVAL")
        self.engine.set_external_universe(list(final_set))
        self._update_realtime_reg(reason="condition_recompute", universe_codes=final_set)

    def _schedule_universe_refresh(self) -> None:
        if self._universe_refresh_scheduled:
            return
        self._universe_refresh_scheduled = True

        def _run() -> None:
            self._universe_refresh_scheduled = False
            self._refresh_universe_from_conditions()

        QTimer.singleShot(300, _run)

    def _refresh_universe_from_conditions(self) -> None:
        final_set = self._evaluate_universe(log_prefix="EVAL")
        self.engine.set_external_universe(list(final_set))
        self._update_realtime_reg(reason="condition_refresh", universe_codes=final_set)
        self._refresh_monitor_results()

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
        universe_codes, _ = self._current_universe()
        self._update_realtime_reg(reason="holdings_received", universe_codes=set(universe_codes))
        self._refresh_positions(market_open=self._is_market_open())

    @pyqtSlot(str)
    def _on_password_required(self, message: str) -> None:
        self._log(f"[실거래] {message}")

    @pyqtSlot(str)
    def _on_condition_raw_log(self, line: str) -> None:
        self._log(line)

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

    def _canonical_condition_name(self, raw_name: str, idx_any) -> str:
        name = str(raw_name or "").strip()
        if name in self.condition_manager.condition_sets_rt:
            return name
        try:
            idx = int(idx_any)
        except Exception:
            idx = None
        if idx is not None:
            for cond_idx, cond_name in getattr(self, "all_conditions", []) or []:
                if int(cond_idx) == idx:
                    mapped = str(cond_name).strip()
                    if mapped in self.condition_manager.condition_sets_rt:
                        self._log(f"[조건] condition_index map idx={idx} '{raw_name}' -> '{mapped}'")
                        return mapped
                    return mapped
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
        self._auto_condition_bootstrap_done = False

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
        openapi = getattr(self.kiwoom_client, "openapi", None)
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
            "connected": bool(getattr(openapi, "connected", False)) if openapi else False,
            "conditions_loaded": bool(getattr(openapi, "conditions_loaded", False)) if openapi else False,
            "selected_condition_name": self._last_selected_condition_name,
            "selected_condition_idx": self._last_selected_condition_idx,
            "send_condition_ret": self._last_send_condition_ret,
            "last_tr_condition_ts": self._last_tr_condition_ts,
            "last_real_condition_ts": self._last_real_condition_ts,
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
            logger.info("[유니버스][diag] %s", json.dumps(diag, ensure_ascii=False))
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

        if self.universe_mode == "test":
            self._log("[MODE] 테스트 모드에서는 조건 실행을 사용할 수 없습니다.")
            return
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
                self._last_send_condition_ret = ret
                self._last_selected_condition_name = name
                self._last_selected_condition_idx = idx
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

        def run() -> None:
            open_flag, reason, now = self._market_state()
            if self.enforce_market_hours and not open_flag:
                self._log_market_guard(reason, now)
                return

            universe, source = self._current_universe()
            self._log(f"[UNIVERSE_SOURCE] {source.upper()}")
            if not universe:
                if source == "test":
                    self._log("[TEST_UNIVERSE] 빈 유니버스 → 매매판단 스킵")
                else:
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

            self.engine.set_external_universe(list(universe))
            self._log(
                f"[AUTO] external_universe_count={len(universe)} mode={self.engine.broker_mode}"
            )
            self._log(f"[유니버스] selector 사용 목록: external_universe 우선 적용 ({len(universe)}건)")
            allow_orders = self.trading_orders_enabled or open_flag
            if not allow_orders:
                self._log("[자동매매] 주문 비활성 상태 → 평가만 수행 또는 스킵")
            self.engine.run_once("combined", allow_orders=allow_orders)
            self._record_no_buy_reasons("run_once", len(universe))
            self._refresh_account_and_positions()
            QTimer.singleShot(200, self._refresh_account_and_positions)
            self._log(f"테스트 실행 1회 완료 ({len(self.strategy.positions)}개 보유)")

        self._run_engine_task("RUN_ONCE", run)

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

        # --- AUTOBOOT: condition auto-run on start ---
        try:
            active_conditions = [t.get("value") for t in self.builder_tokens if t.get("type") == "COND"]
            need_conditions = False
            if active_conditions:
                if self.universe_mode == "condition":
                    need_conditions = True
                elif self.universe_mode == "scanner":
                    try:
                        if getattr(self, "scanner_config", None) and self.scanner_config.candidate_source == "condition":
                            need_conditions = True
                    except Exception:
                        need_conditions = False

            if (
                need_conditions
                and self.auto_run_condition_on_start_checkbox.isChecked()
                and not getattr(self, "_auto_condition_bootstrap_done", False)
            ):
                self._log(f"[조건][AUTOBOOT] start active={len(active_conditions)} universe_mode={self.universe_mode}")
                self._auto_condition_bootstrap_done = True
                self._execute_condition()
                self._log("[조건][AUTOBOOT] end (execute_condition dispatched)")
        except Exception as exc:
            self._log(f"[조건][AUTOBOOT][ERR] {exc}")
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
        if self.universe_mode == "scanner" and not self.scanner_timer.isActive():
            self.scanner_timer.start()
            self._scanner_next_run_at = datetime.datetime.now() + datetime.timedelta(
                seconds=self.scanner_timer.interval() / 1000
            )
            self._update_scan_schedule_ui()
            logger.info(
                "[SCANNER_TIMER] started interval_sec=%s next_run=%s",
                self.scanner_timer.interval() / 1000,
                self._scanner_next_run_at.isoformat(),
            )
            self._log("스캐너 모드 스캔 타이머 시작")

    def on_auto_stop(self) -> None:
        if self.auto_timer.isActive():
            self.auto_timer.stop()
            self.status_label.setText("상태: 매수 종료됨 (자동 정지)")
            self._log("자동 매매 정지")
        if self.scanner_timer.isActive():
            self.scanner_timer.stop()
            self._scanner_next_run_at = None
            self._update_scan_schedule_ui()
            logger.info("[SCANNER_TIMER] stopped")
            self._log("스캐너 모드 스캔 타이머 중지")
        self.auto_trading_active = False
        self.auto_trading_armed = False
        self.trading_orders_enabled = False
        self._auto_condition_bootstrap_done = False

    def _record_no_buy_reasons(self, context: str, universe_count: int) -> None:
        debug = getattr(self.strategy, "last_entry_debug", {}) or {}
        skip_counts = debug.get("skip_counts", {}) or {}
        total_skips = sum(int(v) for v in skip_counts.values()) if skip_counts else 0
        if total_skips <= 0:
            return
        rec = {
            "ts": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "context": context,
            "universe": int(universe_count),
            "skips": {k: int(v) for k, v in skip_counts.items()},
            "samples": list(debug.get("samples", []) or [])[:5],
        }
        self._no_buy_history.append(rec)
        if len(self._no_buy_history) > 500:
            self._no_buy_history = self._no_buy_history[-500:]
        self._log(f"[NO_BUY] context={context} universe={universe_count} skips={rec['skips']} samples={rec['samples']}")

    def _open_no_buy_history(self) -> None:
        dlg = QDialog(self)
        dlg.setWindowTitle("미매수 사유 이력")
        dlg.resize(860, 420)
        lay = QVBoxLayout(dlg)
        table = QTableWidget(0, 5)
        table.setHorizontalHeaderLabels(["시각", "컨텍스트", "유니버스", "스킵요약", "샘플"])
        rows = list(self._no_buy_history)
        table.setRowCount(len(rows))
        for i, rec in enumerate(rows):
            table.setItem(i, 0, QTableWidgetItem(str(rec.get("ts", ""))))
            table.setItem(i, 1, QTableWidgetItem(str(rec.get("context", ""))))
            table.setItem(i, 2, QTableWidgetItem(str(rec.get("universe", 0))))
            skips = rec.get("skips", {}) or {}
            skip_txt = ", ".join([f"{k}:{v}" for k, v in skips.items()])
            table.setItem(i, 3, QTableWidgetItem(skip_txt))
            table.setItem(i, 4, QTableWidgetItem(", ".join([str(x) for x in (rec.get("samples", []) or [])])))
        table.resizeColumnsToContents()
        lay.addWidget(table)
        dlg.exec_()

    def _on_cycle(self) -> None:
        if self._engine_busy:
            self._log("[ENGINE_BUSY] skip: already running (context=AUTO_CYCLE)")
            return

        def run() -> None:
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
                    if self.universe_mode == "scanner":
                        self._log("[SCANNER] market_open -> force_scan_once")
                        self._run_scanner_once(trigger="market_open")
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
            universe, source = self._current_universe()
            self._log(f"[UNIVERSE_SOURCE] {source.upper()}")
            if not universe:
                if source == "test":
                    self._log("[TEST_UNIVERSE] 빈 유니버스 → 매매판단 스킵")
                else:
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
            self.engine.set_external_universe(list(universe))
            if self.enforce_market_hours:
                allow_orders = self.trading_orders_enabled and open_flag
            else:
                allow_orders = self.trading_orders_enabled
            self._log(
                f"[AUTO] broker_mode={self.engine.broker_mode} open_flag={open_flag} enforce_market_hours={self.enforce_market_hours} allow_orders={allow_orders} universe={len(universe)} holdings={len(self.strategy.positions)} max_positions={self.strategy.max_positions}"
            )
            self._log(f"[유니버스] selector 사용 목록: external_universe 우선 적용 ({len(universe)}건)")
            if not allow_orders:
                self._log("[자동매매] 감시모드: 주문 차단 상태로 평가만 진행 또는 스킵")
            self.engine.run_once("combined", allow_orders=allow_orders)
            self._record_no_buy_reasons("auto_cycle", len(universe))
            self._refresh_account_and_positions()

        self._run_engine_task("AUTO_CYCLE", run)

    def _on_scanner_cycle(self) -> None:
        if self._scanner_busy:
            self._log("[SCANNER_BUSY] skip: already running")
            return
        if self._engine_busy:
            self.last_scanner_attempt_ts = datetime.datetime.now()
            next_run = self._scanner_next_run_at.strftime("%H:%M:%S") if self._scanner_next_run_at else "-"
            self._log(f"[SCANNER] skip reason=engine_busy next={next_run}")
            return
        if self.universe_mode != "scanner":
            return

        self._log("[SCANNER] start source=timer_tick")
        logger.info("[SCANNER] start source=timer_tick")
        start = time.perf_counter()
        ok = False
        candidates_count = 0
        applied_count = 0
        try:
            candidates_count, applied_count = self._run_scanner_once(trigger="timer")
            ok = True
        except Exception:  # pragma: no cover - defensive
            logger.exception("[SCANNER] error during timer_tick")
        finally:
            elapsed_ms = (time.perf_counter() - start) * 1000
            logger.info("[SCANNER] end source=timer_tick ok=%s elapsed_ms=%.1f", ok, elapsed_ms)
            self._log(
                f"[SCANNER] end source=timer_tick ok={ok} candidates={candidates_count} "
                f"applied={applied_count} elapsed_ms={elapsed_ms:.1f}"
            )
            interval_sec = self.scanner_timer.interval() / 1000
            self._scanner_next_run_at = datetime.datetime.now() + datetime.timedelta(seconds=interval_sec)
            self._update_scan_schedule_ui()

    def _snapshot_prices(self, codes: Sequence[str]) -> dict[str, Optional[float]]:
        snapshot: dict[str, Optional[float]] = {}
        for code in codes:
            try:
                snapshot[code] = self.engine.get_current_price(code)
            except Exception as exc:  # pragma: no cover - defensive
                snapshot[code] = None
                self._log(f"[SCANNER] price_snapshot_failed code={code} err={exc}")
        return snapshot

    def _get_price_for_tracker(self, code: str) -> Optional[float]:
        try:
            return self.engine.get_current_price(code)
        except Exception as exc:  # pragma: no cover - defensive
            self._log(f"[OPPORTUNITY] price_fetch_failed code={code} err={exc}")
            return None

    def _on_scan_once_clicked(self) -> None:
        if self._scanner_busy:
            self._log("[SCANNER_BUSY] skip: already running")
            return
        if self._engine_busy:
            self._log("[ENGINE_BUSY] skip: already running (context=SCANNER_MANUAL)")
            return

        self._log("[SCANNER] start source=scan_button")
        logger.info("[SCANNER] start source=manual_clicked")
        t0 = time.perf_counter()
        ok = False
        candidates_count = 0
        applied_count = 0
        try:
            if self.universe_mode != "scanner":
                logger.info("[SCANNER] skip: universe_mode=%s (not scanner)", self.universe_mode)
                self._append_scanner_status_ui("스캐너 모드가 아닙니다.")
                return
            candidates_count, applied_count = self._run_scanner_once(trigger="manual")
            ok = True
        except Exception:  # pragma: no cover - defensive
            logger.exception("[SCANNER] error during scan_once")
        finally:
            elapsed_ms = (time.perf_counter() - t0) * 1000
            logger.info("[SCANNER] end source=manual_clicked ok=%s elapsed_ms=%.1f", ok, elapsed_ms)
            self._log(
                f"[SCANNER] end source=scan_button ok={ok} candidates={candidates_count} "
                f"applied={applied_count} elapsed_ms={elapsed_ms:.1f}"
            )

    def _run_scanner_once(self, trigger: str) -> tuple[int, int]:
        self._scanner_busy = True
        try:
            self.last_scanner_attempt_ts = datetime.datetime.now()
            self.last_scanner_trigger = trigger
            self.last_scanner_source = self.scanner_config.candidate_source
            candidates, tr_meta = self._build_scanner_candidates()
            self.last_scanner_tr_meta = tr_meta or {}
            if not candidates:
                self._log("[SCANNER] empty candidates → 스캔 스킵")
                self._append_scanner_status_ui("조건 결과가 없어 스캔을 건너뜁니다.")
                return 0, 0
            scan_result = self.scanner.scan(candidates, self.scanner_current_universe)
            self._last_scan_result = scan_result
            self.scanner_current_universe = scan_result.applied_universe
            self.engine.set_external_universe(scan_result.applied_universe)
            self._update_realtime_reg(
                reason=f"scanner_{trigger}", universe_codes=set(self.scanner_current_universe)
            )
            self.last_scanner_ok_ts = datetime.datetime.now()

            self._log(
                f"[SCANNER] trigger={trigger} raw={scan_result.raw_count} filtered={scan_result.filtered_count} "
                f"desired={len(scan_result.desired_universe)} applied={len(scan_result.applied_universe)} "
                f"realreg={len(self.scanner_current_universe)}"
            )
            self._log(
                f"[SCANNER_CHURN] desired_swaps={scan_result.desired_swaps} allowed={scan_result.allowed_swaps} "
                f"override_extra={scan_result.override_extra} applied_swaps={scan_result.applied_swaps}"
            )
            if scan_result.override_triggered:
                worst_incumbent = None
                if scan_result.current_universe:
                    incumbent_scores = [
                        scan_result.scores.get(code, 0.0) for code in scan_result.current_universe
                    ]
                    worst_incumbent = min(incumbent_scores) if incumbent_scores else None
                examples = ",".join(scan_result.missed_new_strong[:5])
                self._log(
                    f"[SCANNER_OVERRIDE] triggered={scan_result.override_triggered} margin={self.scanner_config.override_margin} "
                    f"worst_incumbent={worst_incumbent} examples=[{examples}]"
                )

            if scan_result.missed_new_strong:
                price_snapshot = self._snapshot_prices(scan_result.missed_new_strong)
                self.opportunity_tracker.record_missed(scan_result, price_snapshot, log_fn=self._log)

            self.opportunity_tracker.evaluate_pending(self._get_price_for_tracker, log_fn=self._log)
            summary = self.opportunity_tracker.summarize(window_minutes=60)
            if summary.get("missed_strong", 0) > 0:
                avg_5m = summary.get("avg_5m", 0.0)
                avg_15m = summary.get("avg_15m", 0.0)
                pos_15m = summary.get("pos_15m", 0.0)
                self._log(
                    f"[OPPORTUNITY_SUMMARY] window=1h missed={summary.get('missed_strong', 0):.0f} "
                    f"avg_5m={avg_5m:.2f} avg_15m={avg_15m:.2f} pos_15m={pos_15m:.1f}%"
                )

            last_ts = scan_result.ts_scan.strftime("%H:%M:%S")
            self.scanner_status_label.setText(
                f"마지막 스캔: {last_ts} / raw={scan_result.raw_count} "
                f"filtered={scan_result.filtered_count} desired={len(scan_result.desired_universe)} "
                f"applied={len(scan_result.applied_universe)}"
            )
            return scan_result.raw_count, len(scan_result.applied_universe)
        finally:
            self._scanner_busy = False

    def _update_scan_schedule_ui(self) -> None:
        if self.scanner_timer.isActive() and self._scanner_next_run_at:
            now = datetime.datetime.now()
            remain = max(0, int((self._scanner_next_run_at - now).total_seconds()))
            self.scan_next_label.setText(
                f"다음 스캔: {self._scanner_next_run_at.strftime('%H:%M:%S')}"
            )
            self.scan_countdown_label.setText(f"남은 시간: {remain}초")
        else:
            self.scan_next_label.setText("다음 스캔: -")
            self.scan_countdown_label.setText("남은 시간: -")

    def _append_scanner_status_ui(self, message: str) -> None:
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        self.scanner_status_label.setText(f"마지막 스캔: {ts} / {message}")

    def _build_scanner_candidates(self) -> tuple[list[str], dict]:
        source = self.scanner_config.candidate_source
        market_code = self.scanner_config.market_code
        top_n = self.scanner_config.top_n
        if source == "condition":
            return list(self.condition_universe), {}
        if source == "opt10030_trade_value":
            codes, meta = self.kiwoom_client.get_rank_candidates_trade_value(market_code, top_n)
            self._log(
                f"[SCANNER_TR] req=opt10030 ok={meta.get('ok', False)} rows={meta.get('rows', 0)} error={meta.get('error', '')}"
            )
            return codes, meta
        if source == "opt10027_change_rate":
            codes, meta = self.kiwoom_client.get_rank_candidates_change_rate(market_code, top_n)
            self._log(
                f"[SCANNER_TR] req=opt10027 ok={meta.get('ok', False)} rows={meta.get('rows', 0)} error={meta.get('error', '')}"
            )
            return codes, meta
        return list(self.condition_universe), {}

    def _on_scanner_source_changed(self) -> None:
        self.scanner_config = ScannerConfig(
            max_watch=self.scanner_config.max_watch,
            max_replacements_per_scan=self.scanner_config.max_replacements_per_scan,
            candidate_source=self.scanner_source_combo.currentData() or "condition",
            market_code=self.scanner_config.market_code,
            top_n=self.scanner_config.top_n,
            override_margin=self.scanner_config.override_margin,
            override_max_extra=self.scanner_config.override_max_extra,
            incumbent_bonus=self.scanner_config.incumbent_bonus,
            strong_rank_cutoff=self.scanner_config.strong_rank_cutoff,
            strong_topk=self.scanner_config.strong_topk,
        )
        self.scanner.config = self.scanner_config

    def _on_scanner_market_changed(self) -> None:
        self.scanner_config = ScannerConfig(
            max_watch=self.scanner_config.max_watch,
            max_replacements_per_scan=self.scanner_config.max_replacements_per_scan,
            candidate_source=self.scanner_config.candidate_source,
            market_code=self.scanner_market_combo.currentData() or "000",
            top_n=self.scanner_config.top_n,
            override_margin=self.scanner_config.override_margin,
            override_max_extra=self.scanner_config.override_max_extra,
            incumbent_bonus=self.scanner_config.incumbent_bonus,
            strong_rank_cutoff=self.scanner_config.strong_rank_cutoff,
            strong_topk=self.scanner_config.strong_topk,
        )
        self.scanner.config = self.scanner_config

    def _run_scanner_healthcheck(self) -> None:
        if self._engine_busy or self._scanner_busy:
            self._log("[HEALTHCHECK] busy 상태로 헬스체크를 건너뜁니다.")
            return
        if self.universe_mode != "scanner":
            self._log("[HEALTHCHECK] 스캐너 모드에서만 실행됩니다.")
            self.scanner_health_text.setPlainText("스캐너 모드에서만 헬스체크를 실행할 수 있습니다.")
            return

        self._scanner_busy = True
        start = time.perf_counter()
        try:
            open_flag, reason, now = self._market_state()
            if self.enforce_market_hours:
                allow_orders = self.trading_orders_enabled and open_flag
            else:
                allow_orders = self.trading_orders_enabled
            holdings = len(self.strategy.positions)
            summary_lines = [
                "[HEALTHCHECK]",
                f"- universe_mode={self.universe_mode}",
                f"- broker_mode={self.engine.broker_mode}",
                f"- allow_orders={allow_orders}",
                "- dry_run=True",
                f"- enforce_market_hours={self.enforce_market_hours}",
                f"- market_open={open_flag} ({reason})",
                f"- holdings={holdings} / max_positions={self.strategy.max_positions}",
                f"- cash={self.strategy.cash:,.0f}",
                "",
                "[PERSIST]",
                f"- data_dir={self.data_dir}",
                f"- settings_ini={settings_ini_path(self.data_dir)}",
                f"- trade_db={self.history_store.db_path}",
                f"- last_backup_ts={self.backup.last_backup_ts}",
                f"- backup_enabled={self.backup_enabled} interval_min={self.backup_interval_min} keep_last={self.backup.keep_last}",
            ]

            scan_result = self._last_scan_result
            candidates = list(self.condition_universe)
            if not scan_result and candidates:
                scan_result = self.scanner.scan(candidates, self.scanner_current_universe)
            if scan_result:
                summary_lines.extend(
                    [
                        "",
                        "[HEALTHCHECK_SCANNER]",
                        f"- last_scan_ts={scan_result.ts_scan.isoformat()}",
                        f"- raw_count={scan_result.raw_count}",
                        f"- filtered_count={scan_result.filtered_count}",
                        f"- desired_count={len(scan_result.desired_universe)}",
                        f"- applied_count={len(scan_result.applied_universe)}",
                        f"- realreg_count={len(self.scanner_current_universe)}",
                        f"- last_attempt={self.last_scanner_attempt_ts}",
                        f"- last_ok={self.last_scanner_ok_ts}",
                        f"- candidate_source={self.scanner_config.candidate_source}",
                        f"- market_code={self.scanner_config.market_code}",
                        f"- tr_trace={self.last_scanner_tr_meta}",
                    ]
                )
            else:
                summary_lines.extend(
                    [
                        "",
                        "[HEALTHCHECK_SCANNER]",
                        f"- last_scan_ts={self.last_scanner_attempt_ts or '없음'}",
                        f"- candidates_count={len(candidates)}",
                        f"- last_attempt={self.last_scanner_attempt_ts}",
                        f"- last_ok={self.last_scanner_ok_ts}",
                        f"- candidate_source={self.scanner_config.candidate_source}",
                        f"- market_code={self.scanner_config.market_code}",
                        f"- tr_trace={self.last_scanner_tr_meta}",
                        "- 스캐너 결과가 없습니다. 조건 실행 또는 스캔 타이머를 확인하세요.",
                    ]
                )

            applied = scan_result.applied_universe if scan_result else []
            if not applied:
                summary_lines.extend(
                    [
                        "",
                        "[HEALTHCHECK_ENGINE]",
                        "- applied_universe=0 (필터 과도/스캔 미실행/조건 결과 없음 가능)",
                    ]
                )
                output = "\n".join(summary_lines)
                self.scanner_health_text.setPlainText(output)
                self._log(
                    f"[HEALTHCHECK] mode={self.universe_mode} broker={self.engine.broker_mode} allow_orders={allow_orders} "
                    f"market_open={open_flag} holdings={holdings} max_pos={self.strategy.max_positions}"
                )
                if scan_result:
                    self._log(
                        f"[HEALTHCHECK_SCANNER] raw={scan_result.raw_count} filtered={scan_result.filtered_count} "
                        f"desired={len(scan_result.desired_universe)} applied=0 realreg={len(self.scanner_current_universe)}"
                    )
                self._log("[HEALTHCHECK_ENGINE] entry_orders=0 skips={} samples=[]")
                return

            entry_orders = self.strategy.evaluate_entry(applied, self.engine.get_current_price)
            debug = self.strategy.last_entry_debug or {}
            skip_counts = debug.get("skip_counts", {})
            samples = debug.get("samples", [])
            budget_per_slot = debug.get("budget_per_slot")
            if holdings >= self.strategy.max_positions:
                skip_counts = dict(skip_counts)
                skip_counts["max_positions_reached"] = holdings
            if not open_flag:
                skip_counts = dict(skip_counts)
                skip_counts["market_closed"] = True

            summary_lines.extend(
                [
                    "",
                    "[HEALTHCHECK_ENGINE]",
                    f"- entry_orders={len(entry_orders)}",
                    f"- budget_per_slot={budget_per_slot:.2f}" if budget_per_slot is not None else "- budget_per_slot=NA",
                    f"- skips={skip_counts}",
                    f"- samples={samples}",
                ]
            )

            output = "\n".join(summary_lines)
            self.scanner_health_text.setPlainText(output)
            self._log(
                f"[HEALTHCHECK] mode={self.universe_mode} broker={self.engine.broker_mode} allow_orders={allow_orders} "
                f"market_open={open_flag} holdings={holdings} max_pos={self.strategy.max_positions}"
            )
            if scan_result:
                self._log(
                    f"[HEALTHCHECK_SCANNER] raw={scan_result.raw_count} filtered={scan_result.filtered_count} "
                    f"desired={len(scan_result.desired_universe)} applied={len(scan_result.applied_universe)} "
                    f"realreg={len(self.scanner_current_universe)}"
                )
            self._log(
                f"[HEALTHCHECK_ENGINE] entry_orders={len(entry_orders)} skips={skip_counts} samples={samples}"
            )
        finally:
            elapsed_ms = (time.perf_counter() - start) * 1000
            self._log(f"[HEALTHCHECK] end elapsed_ms={elapsed_ms:.1f}")
            self._scanner_busy = False


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

    def _current_universe(self) -> tuple[set[str], str]:
        if self.universe_mode == "test":
            return set(self.test_universe), "test"
        if self.universe_mode == "scanner":
            return set(self.scanner_current_universe), "scanner"
        return set(self.condition_universe), "condition"

    def _update_realtime_reg(self, reason: str = "", universe_codes: set[str] | None = None) -> None:
        openapi = getattr(self.kiwoom_client, "openapi", None)
        if not openapi or not getattr(openapi, "connected", False):
            return

        priority: list[str] = []
        try:
            for holding in getattr(self, "real_holdings", []) or []:
                code = str(holding.get("code", "") or "").strip()
                if code:
                    priority.append(code)
        except Exception:
            pass
        try:
            positions = getattr(self.strategy, "positions", {})
            if isinstance(positions, dict):
                iterable = positions.values()
            else:
                iterable = positions
            for pos in iterable:
                code = str(getattr(pos, "symbol", "") or "").strip()
                if code:
                    priority.append(code)
        except Exception:
            pass

        uni = set(universe_codes or set())
        limit = int(getattr(self, "realreg_limit", 100))
        merged: list[str] = []
        seen: set[str] = set()
        for code in priority:
            if code not in seen:
                merged.append(code)
                seen.add(code)
            if len(merged) >= limit:
                break
        if len(merged) < limit:
            for code in sorted(uni):
                if code not in seen:
                    merged.append(code)
                    seen.add(code)
                if len(merged) >= limit:
                    break

        new_set = set(merged)
        if new_set == getattr(self, "_last_realreg_set", set()):
            return

        now = time.time()
        if now - float(getattr(self, "_last_realreg_ts", 0.0)) < 0.5:
            return

        self._last_realreg_set = new_set
        self._last_realreg_ts = now
        openapi.set_real_reg(merged)
        self._log(
            f"[REALREG] update reason={reason} count={len(merged)} "
            f"priority={len(set(priority))} universe={len(uni)}"
        )

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

    def _refresh_account_and_positions(self) -> None:
        self._refresh_account()
        self._refresh_positions(market_open=self._is_market_open())

    def _set_engine_ui_busy(self, busy: bool, context: str = "") -> None:
        if busy:
            if self._status_before_busy is None:
                self._status_before_busy = self.status_label.text()
            QApplication.setOverrideCursor(Qt.WaitCursor)
            status = f"상태: 실행 중... ({context})" if context else "상태: 실행 중..."
            self.status_label.setText(status)
        else:
            if QApplication.overrideCursor() is not None:
                QApplication.restoreOverrideCursor()
            if self._status_before_busy is not None:
                self.status_label.setText(self._status_before_busy)
                self._status_before_busy = None
            else:
                self.status_label.setText("상태: 대기중")

        for button in getattr(self, "_engine_action_buttons", []):
            button.setEnabled(not busy)

    def _run_engine_task(self, context: str, task: Callable[[], None]) -> bool:
        if self._engine_busy:
            self._log(f"[ENGINE_BUSY] skip: already running (context={context})")
            return False
        self._engine_busy = True
        start = time.perf_counter()
        self._set_engine_ui_busy(True, context=context)
        self._log(f"[ENGINE] start context={context}")
        try:
            task()
            return True
        finally:
            elapsed_ms = (time.perf_counter() - start) * 1000
            self._log(f"[ENGINE] end context={context} elapsed_ms={elapsed_ms:.1f}")
            self._engine_busy = False
            self._set_engine_ui_busy(False)

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
        dialog = TradeHistoryDialog(self.history_store, self, name_resolver=self._get_symbol_name, data_dir=self.data_dir)
        dialog.exec_()

    def _load_monitor_snapshot(self) -> None:
        snap = load_json(self.monitor_snapshot_path, default=None)
        if not snap:
            return
        try:
            self._monitor_events = list(snap.get("events", []) or [])
            self._refresh_monitor_events()

            rows = snap.get("rows", []) or []
            if hasattr(self, "monitor_result_table"):
                self.monitor_result_table.setRowCount(len(rows))
                for r, row in enumerate(rows):
                    self.monitor_result_table.setItem(r, 0, QTableWidgetItem(str(row.get("code", ""))))
                    self.monitor_result_table.setItem(r, 1, QTableWidgetItem(str(row.get("name", ""))))
                    self.monitor_result_table.setItem(r, 2, QTableWidgetItem(str(row.get("status", ""))))
                    self.monitor_result_table.setItem(r, 3, QTableWidgetItem(str(row.get("last_ts", ""))))
                self.monitor_result_table.resizeColumnsToContents()

            self._log(
                f"[PERSIST] 모니터 스냅샷 복원 완료 events={len(self._monitor_events)} rows={len(rows)}"
            )
        except Exception as exc:
            self._log(f"[PERSIST][WARN] 모니터 스냅샷 복원 실패: {exc}")

    def _schedule_save_monitor_snapshot(self) -> None:
        if self._persist_monitor_timer.isActive():
            self._persist_monitor_timer.start(500)
        else:
            self._persist_monitor_timer.start(500)

    def _save_monitor_snapshot(self) -> None:
        try:
            rows = []
            if hasattr(self, "monitor_result_table"):
                for r in range(self.monitor_result_table.rowCount()):
                    rows.append(
                        {
                            "code": self.monitor_result_table.item(r, 0).text()
                            if self.monitor_result_table.item(r, 0)
                            else "",
                            "name": self.monitor_result_table.item(r, 1).text()
                            if self.monitor_result_table.item(r, 1)
                            else "",
                            "status": self.monitor_result_table.item(r, 2).text()
                            if self.monitor_result_table.item(r, 2)
                            else "",
                            "last_ts": self.monitor_result_table.item(r, 3).text()
                            if self.monitor_result_table.item(r, 3)
                            else "",
                        }
                    )
            payload = {
                "ts": datetime.datetime.now().isoformat(),
                "events": self._monitor_events[-2000:],
                "rows": rows,
            }
            save_json(self.monitor_snapshot_path, payload)
            logger.info("[PERSIST] monitor snapshot saved: %s", str(self.monitor_snapshot_path))
        except Exception as exc:
            logger.info("[PERSIST] monitor snapshot save failed: %s", exc)

    def _add_monitor_event(self, event_type: str, condition_name: str, code: str, note: str = "") -> None:
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        name = self._get_symbol_name(code) if code else ""
        row = {
            "ts": ts,
            "event": event_type,
            "condition": condition_name,
            "code": code,
            "name": name,
            "note": note,
        }
        self._monitor_events.append(row)
        max_rows = 2000
        if len(self._monitor_events) > max_rows:
            self._monitor_events = self._monitor_events[-max_rows:]
        self._refresh_monitor_events()
        self._schedule_save_monitor_snapshot()

    def _refresh_monitor_results(self) -> None:
        selected_name = self.monitor_condition_combo.currentData()
        if selected_name == "__JOINED__":
            try:
                codes = set(self._evaluate_universe(log_prefix="MONITOR_JOIN") or set())
            except Exception as exc:
                self._log(f"[MONITOR][JOINED][ERR] {exc}")
                codes = set(self.condition_universe or set())
            label = "조인결과"
        elif not selected_name:
            names = list(self.condition_manager.condition_sets_rt.keys())
            codes = set()
            for name in names:
                codes |= self.condition_manager.get_bucket(name, source="rt")
            label = "전체"
        else:
            codes = self.condition_manager.get_bucket(selected_name, source="rt")
            label = str(selected_name)
        self.monitor_result_table.setRowCount(len(codes))
        for row_idx, code in enumerate(sorted(codes)):
            name = self._get_symbol_name(code)
            last_ts = self._monitor_last_update.get(code, "-")
            status = "포함"
            self.monitor_result_table.setItem(row_idx, 0, QTableWidgetItem(code))
            self.monitor_result_table.setItem(row_idx, 1, QTableWidgetItem(name))
            self.monitor_result_table.setItem(row_idx, 2, QTableWidgetItem(str(last_ts)))
            self.monitor_result_table.setItem(row_idx, 3, QTableWidgetItem(status))
        self.monitor_result_table.resizeColumnsToContents()
        last_event = self._monitor_events[-1]["ts"] if self._monitor_events else "-"
        guidance = " (조건 실행 전이거나 이벤트 미수신)"
        if selected_name == "__JOINED__":
            self.monitor_status_label.setText(
                f"마지막 수신: {last_event} / 조인결과: {len(codes)}건 (현재 빌더 기준){guidance if len(codes) == 0 else ''}"
            )
        else:
            self.monitor_status_label.setText(
                f"마지막 수신: {last_event} / {label} 결과: {len(codes)}건{guidance if len(codes) == 0 else ''}"
            )

    def _refresh_monitor_events(self) -> None:
        rows = self._monitor_events
        self.monitor_event_table.setRowCount(len(rows))
        for row_idx, row in enumerate(rows):
            self.monitor_event_table.setItem(row_idx, 0, QTableWidgetItem(row["ts"]))
            self.monitor_event_table.setItem(row_idx, 1, QTableWidgetItem(row["event"]))
            self.monitor_event_table.setItem(row_idx, 2, QTableWidgetItem(row["condition"]))
            self.monitor_event_table.setItem(row_idx, 3, QTableWidgetItem(row["code"]))
            self.monitor_event_table.setItem(row_idx, 4, QTableWidgetItem(row["name"]))
            self.monitor_event_table.setItem(row_idx, 5, QTableWidgetItem(row["note"]))
        self.monitor_event_table.resizeColumnsToContents()

    def _reset_monitor_events(self) -> None:
        self._monitor_events = []
        self.monitor_event_table.setRowCount(0)
        self.monitor_status_label.setText(
            "마지막 수신: - / 현재 결과: 0건 (조건 실행 전이거나 이벤트 미수신)"
        )
        self._schedule_save_monitor_snapshot()

    def _export_monitor_csv(self) -> None:
        base_path, _ = QFileDialog.getSaveFileName(self, "CSV 저장", "", "CSV Files (*.csv)")
        if not base_path:
            return
        base = base_path.rsplit(".csv", 1)[0]
        result_path = base + "_current.csv"
        event_path = base + "_events.csv"
        self._export_table_csv(self.monitor_result_table, result_path)
        self._export_table_csv(self.monitor_event_table, event_path)
        self._log(f"[모니터] CSV 저장 완료: {result_path}, {event_path}")

    def _export_table_csv(self, table: QTableWidget, path: str) -> None:
        import csv

        headers = [table.horizontalHeaderItem(i).text() for i in range(table.columnCount())]
        with open(path, "w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(headers)
            for row in range(table.rowCount()):
                values = []
                for col in range(table.columnCount()):
                    item = table.item(row, col)
                    values.append(item.text() if item else "")
                writer.writerow(values)
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
            universe_codes, _ = self._current_universe()
            self._update_realtime_reg(reason="positions_refresh", universe_codes=set(universe_codes))
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
        selected_monitor = self.monitor_condition_combo.currentData()
        self.monitor_condition_combo.blockSignals(True)
        self.monitor_condition_combo.clear()
        self.monitor_condition_combo.addItem("전체", "")
        self.monitor_condition_combo.addItem("조인결과(최종 유니버스)", "__JOINED__")
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
            self.monitor_condition_combo.addItem(f"{idx}: {name}", name)
        restore_idx = self.monitor_condition_combo.findData(selected_monitor)
        if restore_idx >= 0:
            self.monitor_condition_combo.setCurrentIndex(restore_idx)
        else:
            joined_idx = self.monitor_condition_combo.findData("__JOINED__")
            self.monitor_condition_combo.setCurrentIndex(joined_idx if joined_idx >= 0 else 0)
        self.monitor_condition_combo.blockSignals(False)

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

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt override
        if hasattr(self, "main_tabs"):
            self.settings.setValue("ui/main_tab_index", self.main_tabs.currentIndex())
        self.settings.setValue("ui/window_geometry", self.saveGeometry())
        self._save_monitor_snapshot()
        self._run_backup_ui("exit")
        self.settings.sync()
        super().closeEvent(event)

    def _open_data_dir(self) -> None:
        try:
            path = str(self.data_dir)
            if sys.platform.startswith("win"):
                os.startfile(path)  # noqa: S606,S607
            else:
                import subprocess

                subprocess.Popen(["xdg-open", path])
        except Exception as exc:
            self._log(f"[UI][WARN] 데이터 폴더 열기 실패: {exc}")

    def _change_data_dir(self) -> None:
        try:
            path = QFileDialog.getExistingDirectory(self, "데이터 폴더 선택", str(self.data_dir))
            if not path:
                return
            self.secure_settings.setValue("storage/data_dir", path)
            self.secure_settings.sync()
            QMessageBox.information(
                self,
                "완료",
                "데이터 폴더 경로를 저장했습니다.\n프로그램을 재시작하면 새 폴더에서 자동 복원됩니다.",
            )
            self._log(f"[PERSIST] storage/data_dir updated -> {path}")
            self._refresh_topbar_paths()
        except Exception as exc:
            self._log(f"[UI][WARN] 데이터 폴더 변경 실패: {exc}")

    def _backup_status_path(self) -> Path:
        return self.data_dir / "backups" / "last_status.json"

    def _persist_backup_status(self, ok: bool, out_dir: str, err: str) -> None:
        payload = {
            "ts": self.backup.last_backup_ts,
            "ok": ok,
            "files": int(self.backup.last_backup_count),
            "dir": out_dir or (str(self.backup.last_backup_dir) if self.backup.last_backup_dir else ""),
            "error": err or self.backup.last_backup_error,
        }
        save_json(self._backup_status_path(), payload)
        self._backup_last_payload = payload

    def _load_backup_status(self) -> None:
        payload = load_json(self._backup_status_path(), default=None) or {}
        self._backup_last_payload = payload

    def _update_backup_status_labels(self) -> None:
        payload = getattr(self, "_backup_last_payload", {}) or {}
        ts = payload.get("ts") or "(none)"
        ok = payload.get("ok", None)
        files = payload.get("files", 0)
        out_dir = payload.get("dir", "-")
        err = payload.get("error", "")

        self.last_backup_label.setText(f"LAST: {ts}")
        self.backup_count_label.setText(f"FILES: {files}")
        self.backup_path_label.setText(f"PATH: {out_dir}")
        if ok is True:
            self.backup_status_label.setText("BACKUP: OK")
            self.backup_err_label.setText("")
        elif ok is False:
            self.backup_status_label.setText("BACKUP: FAIL")
            self.backup_err_label.setText(err[:120])
        else:
            self.backup_status_label.setText("BACKUP: (unknown)")
            self.backup_err_label.setText("")
        self._refresh_topbar_paths()

    def _elide_middle(self, text: str, widget: QLabel) -> str:
        fm = QFontMetrics(widget.font())
        width = max(widget.width() - 10, 100)
        return fm.elidedText(text, Qt.ElideMiddle, width)

    def _refresh_topbar_paths(self) -> None:
        full_data = str(self.data_dir)
        self.data_dir_label.setToolTip(full_data)
        self.data_dir_label.setText("DATA: " + self._elide_middle(full_data, self.data_dir_label))

        payload = getattr(self, "_backup_last_payload", {}) or {}
        path_text = str(payload.get("dir") or "-")
        self.backup_path_label.setToolTip(path_text)
        self.backup_path_label.setText("PATH: " + self._elide_middle(path_text, self.backup_path_label))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        try:
            self._refresh_topbar_paths()
        except Exception:
            pass

    def _run_backup_ui(self, reason: str) -> None:
        try:
            self._log(f"[BACKUP] 요청 reason={reason}")
            out = self.backup.run_backup(reason=reason)
            self._persist_backup_status(ok=True, out_dir=str(out), err="")
            self._update_backup_status_labels()
            self._log(f"[BACKUP] 완료 out={out} files={self.backup.last_backup_count}")
        except Exception as exc:
            err = f"{exc}"
            self._persist_backup_status(ok=False, out_dir="", err=err)
            self._update_backup_status_labels()
            self._log(f"[BACKUP][ERR] 실패: {err}")

    def _open_restore_wizard(self) -> None:
        wizard = RestoreWizard(self, current_data_dir=self.data_dir, secure_settings=self.secure_settings)
        wizard.restored.connect(self._on_restored)
        wizard.exec_()

    def _on_restored(self, payload: dict) -> None:
        self._log(f"[RESTORE] result={payload}")
        self._maybe_restore_paper_from_db(trigger="restore_wizard")
        self._refresh_account_and_positions()
        QMessageBox.information(
            self,
            "복원 완료",
            "복원이 완료되었습니다.\n정확한 반영을 위해 프로그램을 재시작하는 것을 권장합니다.",
        )

    def _run_auto_backup(self) -> None:
        self._run_backup_ui("timer")


def main(argv: Optional[List[str]] = None) -> None:
    """Entry point for manual GUI testing."""

    secure = QSettings("Mystock02", "AutoTrader")
    user_dir = secure.value("storage/data_dir", "")
    data_dir = resolve_data_dir(user_dir)
    ensure_data_dirs(data_dir)
    configure_logging(log_dir=(data_dir / "logs"))
    app = QApplication(argv or [])
    window = MainWindow()
    window.show()
    app.exec_()


if __name__ == "__main__":
    main()
