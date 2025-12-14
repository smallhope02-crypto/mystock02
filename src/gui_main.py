"""PyQt5 GUI for the Mystock02 auto-trading playground."""

import datetime
import logging
import sys
from typing import List, Optional

try:
    from PyQt5.QtCore import Qt, QTimer
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
        QMainWindow,
        QMessageBox,
        QPushButton,
        QRadioButton,
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
from .kiwoom_client import KiwoomClient
from .selector import UniverseSelector
from .strategy import Strategy
from .trade_engine import TradeEngine

logger = logging.getLogger(__name__)


class ConfigDialog(QDialog):
    """Dialog to edit Kiwoom credentials and run connection checks."""

    def __init__(self, parent: QWidget, config: AppConfig, client: KiwoomClient):
        super().__init__(parent)
        self.setWindowTitle("연동 설정")
        self.client = client
        self._config = config
        self.result_config: Optional[AppConfig] = None

        self.app_key_edit = QLineEdit(config.app_key)
        self.app_secret_edit = QLineEdit(config.app_secret)
        self.app_secret_edit.setEchoMode(QLineEdit.Password)
        self.account_no_edit = QLineEdit(config.account_no)

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

    def _on_accept(self) -> None:
        self._apply_to_client()
        self.result_config = self._config
        self.accept()


class MainWindow(QMainWindow):
    """PyQt window exposing trading controls, account info, and timers."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Mystock02 Auto Trader")

        self.current_config = load_config()
        self.strategy = Strategy()
        self.kiwoom_client = KiwoomClient(
            account_no=self.current_config.account_no,
            app_key=self.current_config.app_key,
            app_secret=self.current_config.app_secret,
        )
        self.selector = UniverseSelector(kiwoom_client=self.kiwoom_client)
        self.engine = TradeEngine(
            strategy=self.strategy,
            selector=self.selector,
            broker_mode="paper",
            kiwoom_client=self.kiwoom_client,
        )
        self.condition_map = {}

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

        balance_layout = QHBoxLayout()
        self.paper_balance_label = QLabel("모의 잔고(활성): -")
        self.real_balance_label = QLabel("실계좌 예수금: 실거래 모드에서만 표시")
        self.real_balance_label.setStyleSheet("color: gray;")
        self.real_balance_refresh = QPushButton("잔고 새로고침")
        balance_layout.addWidget(self.paper_balance_label)
        balance_layout.addWidget(self.real_balance_label)
        balance_layout.addWidget(self.real_balance_refresh)
        conn_layout.addLayout(balance_layout)

        conn_group.setLayout(conn_layout)
        main.addWidget(conn_group)

        # Condition selector
        cond_group = QGroupBox("조건식 선택")
        cond_layout = QHBoxLayout()
        self.condition_combo = QComboBox()
        self.manual_condition = QLineEdit()
        self.manual_condition.setPlaceholderText("직접 입력 (선택 사항)")
        self.refresh_conditions_btn = QPushButton("조건 새로고침")
        cond_layout.addWidget(QLabel("조건식"))
        cond_layout.addWidget(self.condition_combo)
        cond_layout.addWidget(self.manual_condition)
        cond_layout.addWidget(self.refresh_conditions_btn)
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

        self.cash_input = QDoubleSpinBox()
        self.cash_input.setRange(100_000, 10_000_000_000)
        self.cash_input.setValue(self.strategy.initial_cash)
        self.cash_input.setPrefix("₩")
        self.cash_input.setDecimals(0)

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
        param_layout.addRow("모의 예수금", self.cash_input)
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
        self.positions_table = QTableWidget(0, 4)
        self.positions_table.setHorizontalHeaderLabels(["종목", "수량", "진입가", "최고가"])
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
            self.cash_input,
            self.max_pos_input,
        ):
            widget.valueChanged.connect(self._mark_dirty)

        self.apply_btn.clicked.connect(self.on_apply_strategy)
        self.test_btn.clicked.connect(self.on_run_once)
        self.auto_start_btn.clicked.connect(self.on_auto_start)
        self.auto_stop_btn.clicked.connect(self.on_auto_stop)
        self.config_btn.clicked.connect(self.on_open_config)
        self.openapi_login_button.clicked.connect(self._on_openapi_login)
        self.refresh_conditions_btn.clicked.connect(self._refresh_condition_list)
        self.real_balance_refresh.clicked.connect(self._refresh_real_balance)

    # Event handlers -----------------------------------------------------
    def on_mode_changed(self) -> None:
        mode = "paper" if self.paper_radio.isChecked() else "real"
        self.engine.set_mode(mode)
        self.cash_input.setEnabled(mode == "paper")
        if mode == "real":
            self.real_balance_label.setStyleSheet("color: black;")
        else:
            self.real_balance_label.setStyleSheet("color: gray;")
        self._refresh_account()
        self._update_connection_labels()
        self.status_label.setText("상태: 대기중")

    def on_open_config(self) -> None:
        dialog = ConfigDialog(self, self.current_config, self.kiwoom_client)
        if dialog.exec_() == QDialog.Accepted and dialog.result_config:
            self.current_config = dialog.result_config
            self.engine.update_credentials(self.current_config)
            self._update_connection_labels()

    def _on_openapi_login(self) -> None:
        try:
            self._log("[조건] 로그인 버튼 클릭 - 컨트롤 초기화 확인")
            self._log("[조건] CommConnect 호출 시도")
            self.kiwoom_client.openapi_login_and_load_conditions()
            openapi = self.kiwoom_client.openapi
            if not openapi:
                self._log("[조건] OpenAPI 래퍼가 없습니다. (초기화 실패)")
                return
            if not getattr(openapi, "_enabled", False):
                self._log("[조건] OpenAPI 래퍼가 비활성 상태입니다. 컨트롤 생성 실패 여부를 콘솔에서 확인하세요.")
                return
            if openapi.available:
                if openapi.connected:
                    self._log("[조건] OpenAPI 로그인 완료 - 조건식 로딩 시도")
                    self._refresh_condition_list()
                else:
                    self._log("OpenAPI 로그인 후 다시 시도해 주세요.")
            else:
                self._log("조건식 기능을 사용할 수 없습니다. (OpenAPI 컨트롤 생성 실패)")
        except Exception as exc:  # pragma: no cover - defensive UI guard
            self._log(f"조건식 로그인 실패: {exc}")

    def _selected_condition(self) -> str:
        combo_value = self.condition_combo.currentText().strip()
        if combo_value:
            mapped = self.condition_map.get(combo_value)
            if mapped:
                return mapped[1]
            if ":" in combo_value:
                _, name = combo_value.split(":", 1)
                return name.strip()
            return combo_value
        manual = self.manual_condition.text().strip()
        if manual:
            return manual
        return ""

    def on_apply_strategy(self) -> None:
        params = dict(
            initial_cash=self.cash_input.value(),
            max_positions=self.max_pos_input.value(),
            stop_loss_pct=self.stop_loss_input.value() / 100,
            take_profit_pct=self.take_profit_input.value() / 100,
            trailing_stop_pct=self.trailing_input.value() / 100,
        )
        self.strategy.update_parameters(**params)
        self.engine.set_paper_cash(self.cash_input.value())
        self.dirty_label.hide()
        self.status_label.setText(
            f"전략 적용 완료 ({datetime.datetime.now().strftime('%H:%M:%S')})"
        )
        self._refresh_account()

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

        condition = self._selected_condition() or "default"
        self.engine.run_once(condition)
        self._refresh_account()
        self._refresh_positions()
        self._log(f"테스트 실행 1회 완료 ({len(self.strategy.positions)}개 보유)")

    def on_auto_start(self) -> None:
        if not self.auto_timer.isActive():
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
        condition = self._selected_condition() or "default"
        self.engine.run_once(condition)
        self._refresh_account()
        self._refresh_positions()

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
            try:
                balance = self.kiwoom_client.get_real_balance()
                self.real_balance_label.setStyleSheet("color: black;")
                self.real_balance_label.setText(f"실계좌 예수금(활성): {balance:,.0f}원")
            except Exception as exc:  # pragma: no cover - UI fallback
                self.real_balance_label.setStyleSheet("color: black;")
                self.real_balance_label.setText("실계좌 예수금: 조회 실패")
                self._log(f"실계좌 예수금 조회 실패: {exc}")

            self.paper_balance_label.setText("모의 잔고: 모의 모드에서만 갱신")
        self._update_connection_labels()

    def _refresh_real_balance(self) -> None:
        if self.engine.broker_mode == "paper":
            self._refresh_account()
            self._log("모의 잔고를 새로고침했습니다.")
            return

        try:
            balance = self.kiwoom_client.get_real_balance()
            self.real_balance_label.setText(f"실계좌 예수금(활성): {balance:,.0f}원")
        except Exception as exc:  # pragma: no cover - UI fallback
            self.real_balance_label.setText("실계좌 예수금: 조회 실패")
            self._log(f"실계좌 예수금 조회 실패: {exc}")

    def _refresh_positions(self) -> None:
        positions = list(self.strategy.positions.values())
        self.positions_table.setRowCount(len(positions))
        for row, pos in enumerate(positions):
            self.positions_table.setItem(row, 0, QTableWidgetItem(pos.symbol))
            self.positions_table.setItem(row, 1, QTableWidgetItem(str(pos.quantity)))
            self.positions_table.setItem(row, 2, QTableWidgetItem(f"{pos.entry_price:.2f}"))
            self.positions_table.setItem(row, 3, QTableWidgetItem(f"{pos.highest_price:.2f}"))
        self.positions_table.resizeColumnsToContents()

    def _refresh_condition_list(self) -> None:
        previous = self.condition_combo.currentText()
        self.condition_combo.clear()
        self.condition_map.clear()
        openapi = getattr(self.kiwoom_client, "openapi", None)

        if not openapi or not openapi.available:
            self.condition_combo.addItem("(조건식 기능 비활성)")
            self._log("조건식 기능을 사용할 수 없습니다. (OpenAPI 컨트롤 생성 실패)")
            return
        if not openapi.connected:
            self.condition_combo.addItem("(로그인 필요)")
            self._log("OpenAPI 로그인 후 조건식을 사용할 수 있습니다.")
            return
        if not openapi.conditions_loaded:
            self.condition_combo.addItem("(조건 로딩 중)")
            openapi.load_conditions()
            self._log("조건식 정보를 불러오는 중입니다...")
            return

        try:
            conditions = openapi.get_conditions()
        except Exception as exc:  # pragma: no cover - UI fallback
            self._log(f"조건식 목록 조회 실패: {exc}")
            conditions = []

        if conditions:
            for idx, name in conditions:
                label = f"{idx}: {name}"
                self.condition_combo.addItem(label)
                self.condition_map[label] = (idx, name)
            if previous in self.condition_map:
                self.condition_combo.setCurrentText(previous)
            self._log(f"조건식 목록 {len(conditions)}개 로딩 완료")
        else:
            self.condition_combo.addItem("(조건 없음)")
            self._log("계정에 등록된 조건식이 없습니다. (0150에서 확인해 주세요)")

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
