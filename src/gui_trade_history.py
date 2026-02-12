"""Trade history dialog for viewing stored events."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
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
        self.mode_combo.addItem("모의서버", "sim")
        self.code_input = QLineEdit()
        self.code_input.setPlaceholderText("종목코드 검색")
        form.addRow("시작일", self.start_date)
        form.addRow("종료일", self.end_date)
        form.addRow("모드", self.mode_combo)
        form.addRow("종목코드", self.code_input)
        layout.addLayout(form)

        filter_row = QHBoxLayout()
        self.only_fills_checkbox = QCheckBox("체결만 보기")
        self.only_fills_checkbox.setChecked(True)
        self.include_receipt_checkbox = QCheckBox("접수 이벤트 포함")
        self.include_receipt_checkbox.setChecked(False)
        self.include_balance_checkbox = QCheckBox("잔고(gubun=1) 포함")
        self.include_balance_checkbox.setChecked(False)
        filter_row.addWidget(self.only_fills_checkbox)
        filter_row.addWidget(self.include_receipt_checkbox)
        filter_row.addWidget(self.include_balance_checkbox)
        layout.addLayout(filter_row)

        button_row = QHBoxLayout()
        self.search_button = QPushButton("조회")
        self.export_button = QPushButton("CSV 저장")
        button_row.addWidget(self.search_button)
        button_row.addWidget(self.export_button)
        layout.addLayout(button_row)

        self.table = QTableWidget(0, 11)
        self.table.setHorizontalHeaderLabels(
            [
                "시간",
                "모드",
                "구분(gubun)",
                "종목",
                "매수/매도",
                "상태",
                "주문수량",
                "체결가",
                "체결량",
                "주문번호",
                "체결번호",
            ]
        )
        self.table.setSortingEnabled(True)
        layout.addWidget(self.table)

        self.setLayout(layout)

        self.search_button.clicked.connect(self._load_rows)
        self.export_button.clicked.connect(self._export_csv)
        self.only_fills_checkbox.toggled.connect(self._load_rows)
        self.include_receipt_checkbox.toggled.connect(self._load_rows)
        self.include_balance_checkbox.toggled.connect(self._load_rows)

        self._load_rows()

    @staticmethod
    def _format_side(row: dict) -> str:
        side = str(row.get("side", "") or "").strip()
        event_type = row.get("event_type")
        if event_type == "paper_fill":
            if side == "buy":
                return "매수"
            if side == "sell":
                return "매도"
        if side == "1":
            return "매도"
        if side == "2":
            return "매수"
        return side

    @staticmethod
    def _format_gubun(row: dict) -> str:
        gubun = str(row.get("gubun", "") or "").strip()
        if gubun == "0":
            return "주문/체결"
        if gubun == "1":
            return "잔고"
        return gubun or "-"

    def _is_fill_row(self, row: dict) -> bool:
        if row.get("event_type") == "paper_fill":
            return True
        if str(row.get("gubun", "")).strip() != "0":
            return False
        status = str(row.get("status", "") or "")
        exec_qty = row.get("exec_qty") or 0
        return status == "체결" and exec_qty > 0

    def _should_include_row(self, row: dict) -> bool:
        gubun = str(row.get("gubun", "") or "")
        status = str(row.get("status", "") or "")
        only_fills = self.only_fills_checkbox.isChecked()
        include_receipt = self.include_receipt_checkbox.isChecked()
        include_balance = self.include_balance_checkbox.isChecked()

        if row.get("event_type") == "paper_fill":
            return True if only_fills else True

        if gubun == "1":
            return include_balance and (not only_fills or status == "체결")

        if only_fills:
            if status == "체결":
                return True
            return include_receipt and status == "접수"
        return True if (status != "접수" or include_receipt) else False

    def _load_rows(self) -> None:
        start = self.start_date.date().toString("yyyy-MM-dd") + " 00:00:00"
        end = self.end_date.date().toString("yyyy-MM-dd") + " 23:59:59"
        mode = self.mode_combo.currentData()
        code = self.code_input.text().strip() or None
        rows = [row for row in self.store.query_events(start, end, mode=mode, code=code) if self._should_include_row(row)]
        self.table.setRowCount(len(rows))
        for row_idx, row in enumerate(rows):
            code_val = str(row.get("code", ""))
            name_val = str(row.get("name", "") or "")
            symbol = f"{code_val} {name_val}".strip()
            self.table.setItem(row_idx, 0, QTableWidgetItem(str(row.get("created_at", ""))))
            self.table.setItem(row_idx, 1, QTableWidgetItem(str(row.get("mode", ""))))
            self.table.setItem(row_idx, 2, QTableWidgetItem(self._format_gubun(row)))
            self.table.setItem(row_idx, 3, QTableWidgetItem(symbol))
            self.table.setItem(row_idx, 4, QTableWidgetItem(self._format_side(row)))
            self.table.setItem(row_idx, 5, QTableWidgetItem(str(row.get("status", ""))))
            self.table.setItem(row_idx, 6, QTableWidgetItem(str(row.get("order_qty", ""))))
            self.table.setItem(row_idx, 7, QTableWidgetItem(str(row.get("exec_price", ""))))
            self.table.setItem(row_idx, 8, QTableWidgetItem(str(row.get("exec_qty", ""))))
            self.table.setItem(row_idx, 9, QTableWidgetItem(str(row.get("order_no", ""))))
            self.table.setItem(row_idx, 10, QTableWidgetItem(str(row.get("exec_no", ""))))
        self.table.resizeColumnsToContents()

    def _select_export_mode(self) -> str | None:
        dialog = QMessageBox(self)
        dialog.setWindowTitle("CSV 저장")
        dialog.setText("저장할 CSV 형식을 선택하세요.")
        raw_button = dialog.addButton("원본 이벤트로 저장", QMessageBox.AcceptRole)
        summary_button = dialog.addButton("체결 요약으로 저장", QMessageBox.AcceptRole)
        dialog.addButton("취소", QMessageBox.RejectRole)
        dialog.exec_()
        clicked = dialog.clickedButton()
        if clicked == raw_button:
            return "raw"
        if clicked == summary_button:
            return "summary"
        return None

    def _export_csv(self) -> None:
        export_mode = self._select_export_mode()
        if not export_mode:
            return
        path_str, _ = QFileDialog.getSaveFileName(self, "CSV 저장", "", "CSV Files (*.csv)")
        if not path_str:
            return
        start = self.start_date.date().toString("yyyy-MM-dd") + " 00:00:00"
        end = self.end_date.date().toString("yyyy-MM-dd") + " 23:59:59"
        mode = self.mode_combo.currentData()
        code = self.code_input.text().strip() or None
        rows = self.store.query_events(start, end, mode=mode, code=code, limit=5000)
        if export_mode == "raw":
            self.store.export_csv(rows, Path(path_str))
            return
        summary_rows = self._build_fill_summary(rows)
        self.store.export_csv(summary_rows, Path(path_str))

    def _build_fill_summary(self, rows: list[dict]) -> list[dict]:
        grouped: dict[tuple, dict] = {}
        for row in rows:
            if row.get("event_type") == "paper_fill":
                status = "체결"
            else:
                status = row.get("status")
            if not ((row.get("event_type") == "paper_fill") or (str(row.get("gubun", "")).strip() == "0")):
                continue
            exec_qty = row.get("exec_qty") or 0
            if status != "체결" or exec_qty <= 0:
                continue
            mode = row.get("mode")
            code = row.get("code")
            side = self._format_side(row)
            order_no = row.get("order_no") or row.get("exec_no") or ""
            key = (mode, code, order_no, side)
            exec_price = row.get("exec_price") or 0
            fee = row.get("fee") or 0
            tax = row.get("tax") or 0
            created_at = row.get("created_at") or ""
            name = row.get("name") or ""
            bucket = grouped.setdefault(
                key,
                {
                    "created_at_first": created_at,
                    "created_at_last": created_at,
                    "mode": mode,
                    "code": code,
                    "name": name,
                    "side": side,
                    "order_no": order_no,
                    "fill_count": 0,
                    "total_qty": 0,
                    "vwap": 0.0,
                    "fee_sum": 0,
                    "tax_sum": 0,
                    "_notional": 0,
                },
            )
            if created_at and created_at < bucket["created_at_first"]:
                bucket["created_at_first"] = created_at
            if created_at and created_at > bucket["created_at_last"]:
                bucket["created_at_last"] = created_at
            bucket["fill_count"] += 1
            bucket["total_qty"] += exec_qty
            bucket["_notional"] += exec_qty * exec_price
            bucket["fee_sum"] += fee
            bucket["tax_sum"] += tax

        summary_rows = []
        for bucket in grouped.values():
            total_qty = bucket["total_qty"] or 0
            vwap = bucket["_notional"] / total_qty if total_qty else 0
            bucket["vwap"] = round(vwap, 2)
            bucket.pop("_notional", None)
            summary_rows.append(bucket)
        return summary_rows
