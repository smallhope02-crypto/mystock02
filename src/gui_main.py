+"""Minimal PyQt GUI wiring paper/real modes and strategy parameters."""
+from __future__ import annotations
+
+import logging
+from typing import List
+
+from PyQt5.QtCore import Qt
+from PyQt5.QtWidgets import (
+    QApplication,
+    QButtonGroup,
+    QDoubleSpinBox,
+    QHBoxLayout,
+    QLabel,
+    QLineEdit,
+    QMainWindow,
+    QPushButton,
+    QRadioButton,
+    QSpinBox,
+    QTableWidget,
+    QTableWidgetItem,
+    QVBoxLayout,
+    QWidget,
+)
+
+from .selector import UniverseSelector
+from .strategy import Strategy
+from .trade_engine import TradeEngine
+
+logger = logging.getLogger(__name__)
+
+
+class MainWindow(QMainWindow):
+    """PyQt window exposing trading controls and paper account info."""
+
+    def __init__(self):
+        super().__init__()
+        self.setWindowTitle("Mystock02 Auto Trader")
+
+        self.strategy = Strategy()
+        self.selector = UniverseSelector()
+        self.engine = TradeEngine(strategy=self.strategy, selector=self.selector, broker_mode="paper")
+
+        self.condition_input = QLineEdit()
+        self.condition_input.setPlaceholderText("조건식 이름")
+
+        self.mode_group = QButtonGroup()
+        self.paper_radio = QRadioButton("모의 모드")
+        self.real_radio = QRadioButton("실거래 모드")
+        self.paper_radio.setChecked(True)
+        self.mode_group.addButton(self.paper_radio)
+        self.mode_group.addButton(self.real_radio)
+
+        self.cash_input = QDoubleSpinBox()
+        self.cash_input.setRange(100_000, 10_000_000_000)
+        self.cash_input.setValue(self.strategy.initial_cash)
+        self.cash_input.setPrefix("₩")
+        self.cash_input.setDecimals(0)
+
+        self.max_pos_input = QSpinBox()
+        self.max_pos_input.setRange(1, 50)
+        self.max_pos_input.setValue(self.strategy.max_positions)
+
+        self.set_cash_btn = QPushButton("예수금 설정")
+        self.apply_btn = QPushButton("전략 적용")
+        self.run_btn = QPushButton("1회 실행")
+
+        self.cash_label = QLabel("예수금: 0")
+        self.equity_label = QLabel("평가금액: 0")
+        self.pnl_label = QLabel("평가손익: 0")
+
+        self.positions_table = QTableWidget(0, 3)
+        self.positions_table.setHorizontalHeaderLabels(["종목", "수량", "진입가"])
+
+        self._build_layout()
+        self._connect_signals()
+        self._refresh_account()
+
+    def _build_layout(self):
+        root = QWidget()
+        layout = QVBoxLayout()
+
+        mode_layout = QHBoxLayout()
+        mode_layout.addWidget(self.paper_radio)
+        mode_layout.addWidget(self.real_radio)
+        layout.addLayout(mode_layout)
+
+        layout.addWidget(QLabel("조건식"))
+        layout.addWidget(self.condition_input)
+
+        params_layout = QHBoxLayout()
+        params_layout.addWidget(QLabel("모의 예수금"))
+        params_layout.addWidget(self.cash_input)
+        params_layout.addWidget(QLabel("최대 보유 종목 수"))
+        params_layout.addWidget(self.max_pos_input)
+        layout.addLayout(params_layout)
+
+        buttons_layout = QHBoxLayout()
+        buttons_layout.addWidget(self.set_cash_btn)
+        buttons_layout.addWidget(self.apply_btn)
+        buttons_layout.addWidget(self.run_btn)
+        layout.addLayout(buttons_layout)
+
+        layout.addWidget(self.cash_label)
+        layout.addWidget(self.equity_label)
+        layout.addWidget(self.pnl_label)
+        layout.addWidget(self.positions_table)
+
+        root.setLayout(layout)
+        self.setCentralWidget(root)
+
+    def _connect_signals(self):
+        self.paper_radio.toggled.connect(self.on_mode_changed)
+        self.set_cash_btn.clicked.connect(self.on_set_cash)
+        self.apply_btn.clicked.connect(self.on_apply_strategy)
+        self.run_btn.clicked.connect(self.on_run_once)
+
+    def on_mode_changed(self, checked: bool):
+        mode = "paper" if self.paper_radio.isChecked() else "real"
+        self.engine.set_mode(mode)
+        logger.info("Mode switched to %s", mode)
+
+    def on_set_cash(self):
+        if self.paper_radio.isChecked():
+            self.engine.set_paper_cash(self.cash_input.value())
+            self._refresh_account()
+
+    def on_apply_strategy(self):
+        self.strategy.update_parameters(
+            initial_cash=self.cash_input.value(), max_positions=self.max_pos_input.value()
+        )
+        logger.info(
+            "Strategy updated: cash %.0f, max_positions %d", self.strategy.initial_cash, self.strategy.max_positions
+        )
+
+    def on_run_once(self):
+        condition = self.condition_input.text() or "default"
+        self.engine.run_once(condition)
+        self._refresh_account()
+        self._refresh_positions()
+
+    def _refresh_account(self):
+        summary = self.engine.account_summary()
+        cash = summary.get("cash", 0)
+        equity = summary.get("equity", 0)
+        pnl = summary.get("pnl", 0)
+        pnl_pct = 0
+        if summary.get("cash") is not None and self.strategy.initial_cash:
+            pnl_pct = (equity - self.strategy.initial_cash) / self.strategy.initial_cash * 100
+
+        self.cash_label.setText(f"예수금: {cash:,.0f}")
+        self.equity_label.setText(f"평가금액: {equity:,.0f}")
+        self.pnl_label.setText(f"평가손익: {pnl:,.0f} ({pnl_pct:.2f}%)")
+
+    def _refresh_positions(self):
+        positions = list(self.strategy.positions.values())
+        self.positions_table.setRowCount(len(positions))
+        for row, pos in enumerate(positions):
+            self.positions_table.setItem(row, 0, QTableWidgetItem(pos.symbol))
+            self.positions_table.setItem(row, 1, QTableWidgetItem(str(pos.quantity)))
+            self.positions_table.setItem(row, 2, QTableWidgetItem(f"{pos.entry_price:.2f}"))
+        self.positions_table.resizeColumnsToContents()
+
+
+def main(argv: List[str] | None = None) -> None:
+    """Entry point for manual GUI testing."""
+    app = QApplication(argv or [])
+    window = MainWindow()
+    window.show()
+    app.exec_()
+
+
+if __name__ == "__main__":
+    main()
