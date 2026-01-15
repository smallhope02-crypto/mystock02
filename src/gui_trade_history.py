"""Trade history dialog for viewing stored events."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QComboBox,
    QDateEdit,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from .trade_history_store import TradeHistoryStore


class TradeHistoryDialog(QDialog):
    """Dialog to browse and export trade history."""

    def __init__(self, store: TradeHistoryStore, parent: Optional[QDialog] = None) -> None:
        super().__init__(parent)
        self.store = store
        self.setWindowTitle("매수/매도 이력 조회")
        self.resize(900, 500)

        layout = QVBoxLayout()
        form = QFormLayout()
        self.start_date = QDateEdit()
        self.end_date = QDateEdit()
        self.start_date.setCalendarPopup(True)
        self.end_date.setCalendarPopup(True)
        today = datetime.today().date()
        self.start_date.setDate(today - timedelta(days=7))
        self.end_date.setDate(today)
        self.mode_combo = QComboBox()
        self.mode_combo.addItem("전체", "all")
        self.mode_combo.addItem("모의", "paper")
        self.mode_combo.addItem("실거래", "real")
        self.code_input = QLineEdit()
        self.code_input.setPlaceholderText("종목코드 검색")
        form.addRow("시작일", self.start_date)
        form.addRow("종료일", self.end_date)
        form.addRow("모드", self.mode_combo)
        form.addRow("종목코드", self.code_input)
        layout.addLayout(form)

        button_row = QHBoxLayout()
        self.search_button = QPushButton("조회")
        self.export_button = QPushButton("CSV 저장")
        button_row.addWidget(self.search_button)
        button_row.addWidget(self.export_button)
        layout.addLayout(button_row)

        self.table = QTableWidget(0, 9)
        self.table.setHorizontalHeaderLabels(
            ["시간", "모드", "종목코드", "종목명", "매수/매도", "체결가", "체결량", "주문번호", "상태"]
        )
        self.table.setSortingEnabled(True)
        layout.addWidget(self.table)

        self.setLayout(layout)

        self.search_button.clicked.connect(self._load_rows)
        self.export_button.clicked.connect(self._export_csv)

        self._load_rows()

    def _load_rows(self) -> None:
        start = self.start_date.date().toString("yyyy-MM-dd") + " 00:00:00"
        end = self.end_date.date().toString("yyyy-MM-dd") + " 23:59:59"
        mode = self.mode_combo.currentData()
        code = self.code_input.text().strip() or None
        rows = self.store.query_events(start, end, mode=mode, code=code)
        self.table.setRowCount(len(rows))
        for row_idx, row in enumerate(rows):
            self.table.setItem(row_idx, 0, QTableWidgetItem(str(row.get("created_at", ""))))
            self.table.setItem(row_idx, 1, QTableWidgetItem(str(row.get("mode", ""))))
            self.table.setItem(row_idx, 2, QTableWidgetItem(str(row.get("code", ""))))
            self.table.setItem(row_idx, 3, QTableWidgetItem(str(row.get("name", ""))))
            self.table.setItem(row_idx, 4, QTableWidgetItem(str(row.get("side", ""))))
            self.table.setItem(row_idx, 5, QTableWidgetItem(str(row.get("exec_price", ""))))
            self.table.setItem(row_idx, 6, QTableWidgetItem(str(row.get("exec_qty", ""))))
            self.table.setItem(row_idx, 7, QTableWidgetItem(str(row.get("order_no", ""))))
            self.table.setItem(row_idx, 8, QTableWidgetItem(str(row.get("status", ""))))
        self.table.resizeColumnsToContents()

    def _export_csv(self) -> None:
        path_str, _ = QFileDialog.getSaveFileName(self, "CSV 저장", "", "CSV Files (*.csv)")
        if not path_str:
            return
        start = self.start_date.date().toString("yyyy-MM-dd") + " 00:00:00"
        end = self.end_date.date().toString("yyyy-MM-dd") + " 23:59:59"
        mode = self.mode_combo.currentData()
        code = self.code_input.text().strip() or None
        rows = self.store.query_events(start, end, mode=mode, code=code, limit=5000)
        self.store.export_csv(rows, Path(path_str))
