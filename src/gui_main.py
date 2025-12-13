+"""PyQt5 GUI to orchestrate strategy parameters and trading engine."""
+
+from __future__ import annotations
+
+import logging
+from typing import List
+
+from PyQt5 import QtWidgets
+
+from .trade_engine import TradeEngine
+
+logger = logging.getLogger(__name__)
+
+
+class MainWindow(QtWidgets.QMainWindow):
+    """Main window hosting controls for mode selection, parameters, and logs."""
+
+    def __init__(self) -> None:
+        super().__init__()
+        self.setWindowTitle("Mystock02 Auto Trader")
+        self.trade_engine = TradeEngine()
+        self._build_ui()
+        self._refresh_account_info()
+
+    def _build_ui(self) -> None:
+        central = QtWidgets.QWidget()
+        layout = QtWidgets.QVBoxLayout()
+
+        # Mode selection
+        mode_group = QtWidgets.QGroupBox("모드 설정")
+        mode_layout = QtWidgets.QHBoxLayout()
+        self.paper_radio = QtWidgets.QRadioButton("모의 모드")
+        self.live_radio = QtWidgets.QRadioButton("실거래 모드")
+        self.paper_radio.setChecked(True)
+        mode_layout.addWidget(self.paper_radio)
+        mode_layout.addWidget(self.live_radio)
+        mode_group.setLayout(mode_layout)
+
+        # Strategy inputs
+        param_group = QtWidgets.QGroupBox("전략 파라미터")
+        form = QtWidgets.QFormLayout()
+        self.condition_input = QtWidgets.QLineEdit()
+        self.max_positions_input = QtWidgets.QSpinBox()
+        self.max_positions_input.setRange(1, 50)
+        self.max_positions_input.setValue(self.trade_engine.strategy.parameters.max_positions)
+        self.paper_cash_input = QtWidgets.QDoubleSpinBox()
+        self.paper_cash_input.setMaximum(1_000_000_000)
+        self.paper_cash_input.setValue(self.trade_engine.paper_broker.initial_cash)
+        self.strategy_cash_input = QtWidgets.QDoubleSpinBox()
+        self.strategy_cash_input.setMaximum(1_000_000_000)
+        self.strategy_cash_input.setValue(self.trade_engine.strategy.cash)
+        form.addRow("조건식", self.condition_input)
+        form.addRow("최대 보유 종목 수", self.max_positions_input)
+        form.addRow("모의 예수금", self.paper_cash_input)
+        form.addRow("초기 예수금", self.strategy_cash_input)
+        param_group.setLayout(form)
+
+        # Buttons
+        button_layout = QtWidgets.QHBoxLayout()
+        self.apply_button = QtWidgets.QPushButton("전략 적용")
+        self.run_button = QtWidgets.QPushButton("1회 실행")
+        self.reset_paper_button = QtWidgets.QPushButton("예수금 설정")
+        button_layout.addWidget(self.apply_button)
+        button_layout.addWidget(self.run_button)
+        button_layout.addWidget(self.reset_paper_button)
+
+        # Tables / info
+        self.position_table = QtWidgets.QTableWidget(0, 5)
+        self.position_table.setHorizontalHeaderLabels(
+            ["종목", "수량", "매입가", "현재가", "평가금액"]
+        )
+        self.position_table.horizontalHeader().setStretchLastSection(True)
+
+        self.cash_label = QtWidgets.QLabel()
+        self.portfolio_label = QtWidgets.QLabel()
+        self.pnl_label = QtWidgets.QLabel()
+
+        info_layout = QtWidgets.QHBoxLayout()
+        info_layout.addWidget(self.cash_label)
+        info_layout.addWidget(self.portfolio_label)
+        info_layout.addWidget(self.pnl_label)
+
+        layout.addWidget(mode_group)
+        layout.addWidget(param_group)
+        layout.addLayout(button_layout)
+        layout.addLayout(info_layout)
+        layout.addWidget(self.position_table)
+        central.setLayout(layout)
+        self.setCentralWidget(central)
+
+        # Signals
+        self.apply_button.clicked.connect(self._apply_strategy)
+        self.run_button.clicked.connect(self._run_once)
+        self.reset_paper_button.clicked.connect(self._reset_paper_cash)
+        self.paper_radio.toggled.connect(self._handle_mode_toggle)
+
+    def _handle_mode_toggle(self) -> None:
+        mode = "paper" if self.paper_radio.isChecked() else "live"
+        self.trade_engine.set_mode(mode)
+        self._refresh_account_info()
+
+    def _apply_strategy(self) -> None:
+        initial_cash = self.strategy_cash_input.value()
+        max_positions = self.max_positions_input.value()
+        mode = "paper" if self.paper_radio.isChecked() else "live"
+        self.trade_engine.set_mode(mode, initial_cash=initial_cash, max_positions=max_positions)
+        self._refresh_account_info()
+
+    def _reset_paper_cash(self) -> None:
+        cash = self.paper_cash_input.value()
+        self.trade_engine.set_mode("paper", initial_cash=cash)
+        self.paper_radio.setChecked(True)
+        self._refresh_account_info()
+
+    def _run_once(self) -> None:
+        condition = self.condition_input.text() or "default"
+        signals = self.trade_engine.run_once(condition)
+        for signal in signals:
+            logger.info(signal)
+        self._refresh_account_info()
+
+    def _refresh_account_info(self) -> None:
+        summary = self.trade_engine.account_summary()
+        self.cash_label.setText(f"예수금: {summary['cash']:.0f}")
+        self.portfolio_label.setText(f"평가금액: {summary['portfolio_value']:.0f}")
+        self.pnl_label.setText(f"손익%: {summary['profit_loss_pct']:.2f}%")
+        self._populate_positions(self.trade_engine.positions_snapshot())
+
+    def _populate_positions(self, positions: List[dict]) -> None:
+        self.position_table.setRowCount(len(positions))
+        for row, pos in enumerate(positions):
+            self.position_table.setItem(row, 0, QtWidgets.QTableWidgetItem(pos["symbol"]))
+            self.position_table.setItem(row, 1, QtWidgets.QTableWidgetItem(str(pos["quantity"])))
+            self.position_table.setItem(row, 2, QtWidgets.QTableWidgetItem(f"{pos['entry_price']:.2f}"))
+            self.position_table.setItem(row, 3, QtWidgets.QTableWidgetItem(f"{pos['market_price']:.2f}"))
+            self.position_table.setItem(row, 4, QtWidgets.QTableWidgetItem(f"{pos['market_value']:.2f}"))
+
+
+def run_gui() -> None:
+    import sys
+
+    logging.basicConfig(level=logging.INFO)
+    app = QtWidgets.QApplication(sys.argv)
+    window = MainWindow()
+    window.show()
+    sys.exit(app.exec_())
+
+
+if __name__ == "__main__":
+    run_gui()
