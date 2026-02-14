"""Trade history dialog for viewing stored events."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor
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
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .performance_analyzer import build_closed_lots, load_fills
from .trade_history_store import TradeHistoryStore


class TradeHistoryDialog(QDialog):
    """Dialog to browse and export trade history."""

    def __init__(
        self,
        store: TradeHistoryStore,
        parent: Optional[QDialog] = None,
        name_resolver=None,
        data_dir: Path | str | None = None,
    ) -> None:
        super().__init__(parent)
        self.store = store
        self.name_resolver = name_resolver
        self.data_dir = Path(data_dir) if data_dir else None
        self.setWindowTitle("매수/매도 이력 조회")
        self.resize(1180, 620)

        root = QVBoxLayout()
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
        root.addLayout(form)

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
        root.addLayout(filter_row)

        button_row = QHBoxLayout()
        self.search_button = QPushButton("조회")
        self.export_button = QPushButton("CSV 저장")
        self.summary_label = QLabel("순손익: 0 / 0.00%")
        button_row.addWidget(self.search_button)
        button_row.addWidget(self.export_button)
        button_row.addStretch(1)
        button_row.addWidget(self.summary_label)
        root.addLayout(button_row)

        self.tabs = QTabWidget()

        event_tab = QWidget()
        event_layout = QVBoxLayout(event_tab)
        self.table = QTableWidget(0, 14)
        self.table.setHorizontalHeaderLabels(
            [
                "시간",
                "모드",
                "구분(gubun)",
                "종목코드",
                "종목명",
                "매수/매도",
                "상태",
                "주문수량",
                "체결가",
                "체결량",
                "순손익",
                "순손익률(%)",
                "주문번호",
                "체결번호",
            ]
        )
        self.table.setSortingEnabled(True)
        event_layout.addWidget(self.table)
        self.tabs.addTab(event_tab, "체결 로그")

        pnl_tab = QWidget()
        pnl_layout = QVBoxLayout(pnl_tab)
        self.pnl_table = QTableWidget(0, 9)
        self.pnl_table.setHorizontalHeaderLabels(
            [
                "종목코드",
                "종목명",
                "진입시각",
                "청산시각",
                "수량",
                "진입가",
                "청산가",
                "순손익(원)",
                "수익률(%)",
            ]
        )
        pnl_layout.addWidget(self.pnl_table)
        self.tabs.addTab(pnl_tab, "거래 요약(손익)")

        no_buy_tab = QWidget()
        no_buy_layout = QVBoxLayout(no_buy_tab)
        self.no_buy_table = QTableWidget(0, 5)
        self.no_buy_table.setHorizontalHeaderLabels(["시각", "컨텍스트", "종목", "사유", "상세"])
        no_buy_layout.addWidget(self.no_buy_table)
        self.tabs.addTab(no_buy_tab, "미매수 사유")

        root.addWidget(self.tabs)
        self.setLayout(root)

        self.search_button.clicked.connect(self._load_rows)
        self.export_button.clicked.connect(self._export_csv)
        self.only_fills_checkbox.toggled.connect(self._load_rows)
        self.include_receipt_checkbox.toggled.connect(self._load_rows)
        self.include_balance_checkbox.toggled.connect(self._load_rows)

        self._load_rows()

    def _resolve_name(self, code: str, name: str | None) -> str:
        text = str(name or "").strip()
        if text:
            return text
        try:
            if self.name_resolver and code:
                return str(self.name_resolver(code) or "").strip()
        except Exception:
            return ""
        return ""

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
            return True
        if gubun == "1":
            return include_balance and (not only_fills or status == "체결")
        if only_fills:
            if status == "체결":
                return True
            return include_receipt and status == "접수"
        return status != "접수" or include_receipt

    def _extract_fill(self, row: dict) -> tuple[str, int, int] | None:
        if not self._is_fill_row(row):
            return None
        side = self._format_side(row)
        qty = int(row.get("exec_qty") or row.get("order_qty") or 0)
        price = int(row.get("exec_price") or row.get("order_price") or 0)
        if side not in {"매수", "매도"} or qty <= 0 or price <= 0:
            return None
        return side, qty, price

    def _compute_row_pnl(self, rows: list[dict]) -> tuple[dict[int, tuple[int, float]], int, float]:
        fifo: dict[str, list[list[int]]] = {}
        per_row: dict[int, tuple[int, float]] = {}
        total_pnl = 0
        total_cost = 0
        for row in rows:
            row_id = int(row.get("id") or 0)
            code = str(row.get("code") or "").strip()
            fill = self._extract_fill(row)
            if not code or not fill:
                continue
            side, qty, price = fill
            if side == "매수":
                fifo.setdefault(code, []).append([qty, price])
                continue

            sell_left = qty
            matched_cost = 0
            matched_qty = 0
            lots = fifo.get(code, [])
            while sell_left > 0 and lots:
                lot_qty, lot_price = lots[0]
                use_qty = min(lot_qty, sell_left)
                matched_qty += use_qty
                matched_cost += use_qty * lot_price
                lot_qty -= use_qty
                sell_left -= use_qty
                if lot_qty <= 0:
                    lots.pop(0)
                else:
                    lots[0][0] = lot_qty
            if matched_qty <= 0:
                continue
            gross = (price * matched_qty) - matched_cost
            fee = int(row.get("fee") or 0)
            tax = int(row.get("tax") or 0)
            net = gross - fee - tax
            pct = (net / matched_cost * 100.0) if matched_cost > 0 else 0.0
            per_row[row_id] = (net, pct)
            total_pnl += net
            total_cost += matched_cost

        total_pct = (total_pnl / total_cost * 100.0) if total_cost > 0 else 0.0
        return per_row, total_pnl, total_pct

    def _set_pnl_item(self, table: QTableWidget, row_idx: int, col: int, text: str, value: float) -> None:
        item = QTableWidgetItem(text)
        if value > 0:
            item.setForeground(QColor("red"))
        elif value < 0:
            item.setForeground(QColor("blue"))
        item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        table.setItem(row_idx, col, item)

    def _load_rows(self) -> None:
        start = self.start_date.date().toString("yyyy-MM-dd") + " 00:00:00"
        end = self.end_date.date().toString("yyyy-MM-dd") + " 23:59:59"
        mode = self.mode_combo.currentData()
        code = self.code_input.text().strip() or None
        rows = self.store.query_events(start, end, mode=mode, code=code, order_by="created_at ASC", limit=5000)
        rows = [row for row in rows if self._should_include_row(row)]
        row_pnl_map, total_pnl, total_pct = self._compute_row_pnl(rows)

        self.table.setRowCount(len(rows))
        for row_idx, row in enumerate(rows):
            row_id = int(row.get("id") or 0)
            code_val = str(row.get("code", "") or "")
            name_val = self._resolve_name(code_val, str(row.get("name", "") or ""))
            self.table.setItem(row_idx, 0, QTableWidgetItem(str(row.get("created_at", ""))))
            self.table.setItem(row_idx, 1, QTableWidgetItem(str(row.get("mode", ""))))
            self.table.setItem(row_idx, 2, QTableWidgetItem(self._format_gubun(row)))
            self.table.setItem(row_idx, 3, QTableWidgetItem(code_val))
            self.table.setItem(row_idx, 4, QTableWidgetItem(name_val))
            self.table.setItem(row_idx, 5, QTableWidgetItem(self._format_side(row)))
            self.table.setItem(row_idx, 6, QTableWidgetItem(str(row.get("status", ""))))
            self.table.setItem(row_idx, 7, QTableWidgetItem(str(row.get("order_qty", ""))))
            self.table.setItem(row_idx, 8, QTableWidgetItem(str(row.get("exec_price", ""))))
            self.table.setItem(row_idx, 9, QTableWidgetItem(str(row.get("exec_qty", ""))))
            pnl = row_pnl_map.get(row_id)
            if pnl:
                self._set_pnl_item(self.table, row_idx, 10, f"{pnl[0]:,}", pnl[0])
                self._set_pnl_item(self.table, row_idx, 11, f"{pnl[1]:.2f}", pnl[1])
            else:
                self.table.setItem(row_idx, 10, QTableWidgetItem(""))
                self.table.setItem(row_idx, 11, QTableWidgetItem(""))
            self.table.setItem(row_idx, 12, QTableWidgetItem(str(row.get("order_no", ""))))
            self.table.setItem(row_idx, 13, QTableWidgetItem(str(row.get("exec_no", ""))))
        self.table.resizeColumnsToContents()

        self.summary_label.setText(f"순손익: {total_pnl:,} / {total_pct:.2f}%")
        self.summary_label.setStyleSheet("color: red;" if total_pnl > 0 else "color: blue;" if total_pnl < 0 else "")

        self._refresh_pnl_summary(start, end, mode)
        self._refresh_no_buy_tab()

    def _refresh_pnl_summary(self, start: str, end: str, mode: str) -> None:
        start_dt = datetime.strptime(start, "%Y-%m-%d %H:%M:%S")
        end_dt = datetime.strptime(end, "%Y-%m-%d %H:%M:%S")
        fills = load_fills(self.store, start_dt, end_dt, mode_filter=mode)
        lots = build_closed_lots(fills)
        self.pnl_table.setRowCount(len(lots))
        for idx, lot in enumerate(lots):
            name = self._resolve_name(lot.code, lot.name)
            self.pnl_table.setItem(idx, 0, QTableWidgetItem(lot.code))
            self.pnl_table.setItem(idx, 1, QTableWidgetItem(name))
            self.pnl_table.setItem(idx, 2, QTableWidgetItem(lot.entry_ts.strftime("%Y-%m-%d %H:%M:%S")))
            self.pnl_table.setItem(idx, 3, QTableWidgetItem(lot.exit_ts.strftime("%Y-%m-%d %H:%M:%S")))
            self.pnl_table.setItem(idx, 4, QTableWidgetItem(str(lot.qty)))
            self.pnl_table.setItem(idx, 5, QTableWidgetItem(str(lot.entry_price)))
            self.pnl_table.setItem(idx, 6, QTableWidgetItem(str(lot.exit_price)))
            ret = (lot.net_pnl / (lot.entry_price * lot.qty) * 100.0) if lot.entry_price and lot.qty else 0.0
            self._set_pnl_item(self.pnl_table, idx, 7, f"{lot.net_pnl:,}", lot.net_pnl)
            self._set_pnl_item(self.pnl_table, idx, 8, f"{ret:.2f}", ret)
        self.pnl_table.resizeColumnsToContents()

    def _refresh_no_buy_tab(self) -> None:
        if not self.data_dir:
            self.no_buy_table.setRowCount(0)
            return
        path = self.data_dir / "opportunity" / "buy_decisions.csv"
        if not path.exists():
            self.no_buy_table.setRowCount(1)
            self.no_buy_table.setItem(0, 0, QTableWidgetItem("파일 없음"))
            self.no_buy_table.setItem(0, 4, QTableWidgetItem(str(path)))
            return
        import csv

        rows = []
        with path.open("r", newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                rows.append(row)
        rows = rows[-300:]
        self.no_buy_table.setRowCount(len(rows))
        for i, row in enumerate(rows):
            self.no_buy_table.setItem(i, 0, QTableWidgetItem(str(row.get("ts", ""))))
            self.no_buy_table.setItem(i, 1, QTableWidgetItem(str(row.get("context", ""))))
            self.no_buy_table.setItem(i, 2, QTableWidgetItem(str(row.get("symbol", ""))))
            self.no_buy_table.setItem(i, 3, QTableWidgetItem(str(row.get("reason", ""))))
            self.no_buy_table.setItem(i, 4, QTableWidgetItem(str(row.get("detail", ""))))
        self.no_buy_table.resizeColumnsToContents()

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
            name = self._resolve_name(str(code or ""), row.get("name") or "")
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
            bucket["fill_count"] += int(exec_qty > 0)
            bucket["total_qty"] += int(exec_qty)
            bucket["_notional"] += int(exec_price) * int(exec_qty)
            bucket["fee_sum"] += int(fee)
            bucket["tax_sum"] += int(tax)

        result = []
        for bucket in grouped.values():
            qty = bucket["total_qty"]
            notional = bucket.pop("_notional")
            bucket["vwap"] = round(notional / qty, 4) if qty else 0
            result.append(bucket)
        result.sort(key=lambda r: (r["created_at_first"], r["mode"], r["code"]))
        return result
