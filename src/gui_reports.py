"""Reports UI for performance summaries."""

from __future__ import annotations

import csv
import datetime
from pathlib import Path
from typing import Optional

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import (
    QComboBox,
    QDateEdit,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .performance_analyzer import load_fills
from .performance_modes import (
    WinLossMode,
    build_trade_units,
    summarize_by_symbol_units,
    summarize_daily_units,
)
from .trade_history_store import TradeHistoryStore


class ReportsWidget(QWidget):
    def __init__(
        self,
        store: TradeHistoryStore,
        reports_dir: Path | str,
        parent: Optional[QWidget] = None,
        name_resolver=None,
    ) -> None:
        super().__init__(parent)
        self.store = store
        self.reports_dir = Path(reports_dir)
        (self.reports_dir / "snapshots").mkdir(parents=True, exist_ok=True)
        (self.reports_dir / "exports").mkdir(parents=True, exist_ok=True)
        self._last_units = []
        self._last_symbol_perf = []
        self._last_daily = None
        self.name_resolver = name_resolver
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout()
        controls = QHBoxLayout()

        self.start_date = QDateEdit()
        self.end_date = QDateEdit()
        self.start_date.setCalendarPopup(True)
        self.end_date.setCalendarPopup(True)
        today = datetime.date.today()
        self.start_date.setDate(today)
        self.end_date.setDate(today)
        self.today_btn = QPushButton("오늘")

        self.mode_combo = QComboBox()
        self.mode_combo.addItem("전체", "all")
        self.mode_combo.addItem("모의", "paper")
        self.mode_combo.addItem("실거래", "real")
        self.mode_combo.addItem("모의서버", "sim")

        self.winloss_combo = QComboBox()
        self.winloss_combo.addItem("왕복거래 기준(청산 1건=1거래)", WinLossMode.ROUND_TRIP)
        self.winloss_combo.addItem("매도체결 기준(매도 1건=1거래)", WinLossMode.SELL_FILL)

        self.run_btn = QPushButton("리포트 생성")
        self.export_symbol_btn = QPushButton("CSV 저장: 종목성과")
        self.export_daily_btn = QPushButton("CSV 저장: 당일보고서")

        controls.addWidget(QLabel("시작"))
        controls.addWidget(self.start_date)
        controls.addWidget(QLabel("종료"))
        controls.addWidget(self.end_date)
        controls.addWidget(self.today_btn)
        controls.addWidget(QLabel("모드"))
        controls.addWidget(self.mode_combo)
        controls.addWidget(QLabel("승패기준"))
        controls.addWidget(self.winloss_combo)
        controls.addWidget(self.run_btn)
        controls.addWidget(self.export_symbol_btn)
        controls.addWidget(self.export_daily_btn)
        layout.addLayout(controls)

        self.status_label = QLabel("마지막 갱신: -")
        layout.addWidget(self.status_label)

        self.tabs = QTabWidget()

        self.symbol_table = QTableWidget(0, 19)
        self.symbol_table.setHorizontalHeaderLabels(
            [
                "종목코드",
                "종목명",
                "거래수(청산)",
                "성공",
                "실패",
                "성공률(%)",
                "매수금액",
                "매도금액",
                "실현손익(세전)",
                "수수료",
                "세금",
                "실현손익(세후)",
                "수익률(%)",
                "평균손익",
                "평균성공",
                "평균실패",
                "PF(프로핏팩터)",
                "평균보유(분)",
                "최근거래이력",
            ]
        )
        self.symbol_table.setSortingEnabled(True)
        symbol_tab = QWidget()
        symbol_layout = QVBoxLayout()
        symbol_layout.addWidget(self.symbol_table)
        symbol_tab.setLayout(symbol_layout)
        self.tabs.addTab(symbol_tab, "매매종목 성과")

        report_tab = QWidget()
        report_layout = QVBoxLayout()
        self.summary_label = QLabel("요약: -")
        report_layout.addWidget(self.summary_label)

        self.bucket_table = QTableWidget(0, 4)
        self.bucket_table.setHorizontalHeaderLabels(["시간대", "거래수", "성공률(%)", "실현손익(세후)"])
        self.top_table = QTableWidget(0, 5)
        self.top_table.setHorizontalHeaderLabels(["종목코드", "종목명", "거래수", "성공률(%)", "실현손익(세후)"])
        self.bottom_table = QTableWidget(0, 5)
        self.bottom_table.setHorizontalHeaderLabels(["종목코드", "종목명", "거래수", "성공률(%)", "실현손익(세후)"])
        report_layout.addWidget(QLabel("시간대별 성과(30분)"))
        report_layout.addWidget(self.bucket_table)
        report_layout.addWidget(QLabel("상위 종목 Top 10"))
        report_layout.addWidget(self.top_table)
        report_layout.addWidget(QLabel("하위 종목 Bottom 10"))
        report_layout.addWidget(self.bottom_table)
        report_tab.setLayout(report_layout)
        self.tabs.addTab(report_tab, "당일 매매보고서")

        layout.addWidget(self.tabs)
        self.setLayout(layout)

        self.today_btn.clicked.connect(self._set_today)
        self.run_btn.clicked.connect(self._run_report)
        self.export_symbol_btn.clicked.connect(self._export_symbol_csv)
        self.export_daily_btn.clicked.connect(self._export_daily_csv)

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

    def _set_signed_item(self, table: QTableWidget, row: int, col: int, value: float, fmt: str = "{:.2f}") -> None:
        text = fmt.format(value)
        item = QTableWidgetItem(text)
        if value > 0:
            item.setForeground(QColor("red"))
        elif value < 0:
            item.setForeground(QColor("blue"))
        item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        table.setItem(row, col, item)

    def _recent_unit_history(self, units, code: str, limit: int = 3) -> str:
        rows = [u for u in units if u.code == code]
        rows.sort(key=lambda x: x.exit_ts, reverse=True)
        chunks = []
        for u in rows[:limit]:
            tag = "성공" if u.net_pnl > 0 else "실패" if u.net_pnl < 0 else "보합"
            chunks.append(f"{u.exit_ts.strftime('%m-%d %H:%M')} {tag} {u.net_pnl:+,}")
        return " | ".join(chunks)

    def _set_today(self) -> None:
        today = datetime.date.today()
        self.start_date.setDate(today)
        self.end_date.setDate(today)

    def _run_report(self) -> None:
        start_dt = datetime.datetime.combine(self.start_date.date().toPyDate(), datetime.time(0, 0))
        end_dt = datetime.datetime.combine(self.end_date.date().toPyDate(), datetime.time(23, 59, 59))
        mode = self.mode_combo.currentData()
        winloss_mode = self.winloss_combo.currentData()

        def work() -> None:
            try:
                fills = load_fills(self.store, start_dt, end_dt, mode_filter=mode)
                units = build_trade_units(fills, winloss_mode)
                symbol_perf = summarize_by_symbol_units(units)
                daily = summarize_daily_units(units)
                self._last_units = units
                self._last_symbol_perf = symbol_perf
                self._last_daily = daily
                self._update_tables(symbol_perf, daily, winloss_mode, fills, units)
                self._save_snapshot(start_dt, end_dt, mode, winloss_mode, fills, units, symbol_perf, daily)
            except Exception as exc:
                import logging

                logger = logging.getLogger(__name__)
                logger.exception("[REPORT][ERROR] %s", exc)
                QMessageBox.critical(self, "리포트 오류", f"리포트 생성 중 오류: {exc}")
                return

        QTimer.singleShot(0, work)

    def _update_tables(self, symbol_perf, daily, winloss_mode, fills, units) -> None:
        now = datetime.datetime.now().strftime("%H:%M:%S")
        self.status_label.setText(
            f"마지막 갱신: {now} / fills={len(fills)} / units={len(units)} / 종목={len(symbol_perf)} / 순손익={daily.net_pnl_sum if daily else 0}"
        )
        trade_label = "거래수(왕복)" if winloss_mode == WinLossMode.ROUND_TRIP else "거래수(매도체결)"
        self.symbol_table.horizontalHeaderItem(2).setText(trade_label)

        self.symbol_table.setRowCount(len(symbol_perf))
        for row_idx, perf in enumerate(symbol_perf):
            self.symbol_table.setItem(row_idx, 0, QTableWidgetItem(perf.code))
            self.symbol_table.setItem(row_idx, 1, QTableWidgetItem(self._resolve_name(perf.code, perf.name)))
            self.symbol_table.setItem(row_idx, 2, QTableWidgetItem(str(perf.trades)))
            self.symbol_table.setItem(row_idx, 3, QTableWidgetItem(str(perf.wins)))
            self.symbol_table.setItem(row_idx, 4, QTableWidgetItem(str(perf.losses)))
            self.symbol_table.setItem(row_idx, 5, QTableWidgetItem(f"{perf.win_rate:.2f}"))
            self.symbol_table.setItem(row_idx, 6, QTableWidgetItem(f"{perf.buy_amount:,}"))
            self.symbol_table.setItem(row_idx, 7, QTableWidgetItem(f"{perf.sell_amount:,}"))
            gross = perf.gross_profit_sum + perf.gross_loss_sum
            self.symbol_table.setItem(row_idx, 8, QTableWidgetItem(f"{gross:,}"))
            self.symbol_table.setItem(row_idx, 9, QTableWidgetItem(f"{perf.fee_sum:,}"))
            self.symbol_table.setItem(row_idx, 10, QTableWidgetItem(f"{perf.tax_sum:,}"))
            self._set_signed_item(self.symbol_table, row_idx, 11, float(perf.net_pnl_sum), "{:+,.0f}")
            self._set_signed_item(self.symbol_table, row_idx, 12, float(perf.return_pct), "{:+.2f}")
            self.symbol_table.setItem(row_idx, 13, QTableWidgetItem(f"{perf.avg_pnl:.2f}"))
            self.symbol_table.setItem(row_idx, 14, QTableWidgetItem(f"{perf.avg_win:.2f}"))
            self.symbol_table.setItem(row_idx, 15, QTableWidgetItem(f"{perf.avg_loss:.2f}"))
            self.symbol_table.setItem(row_idx, 16, QTableWidgetItem(f"{perf.profit_factor:.2f}"))
            hold = perf.avg_hold_minutes if perf.avg_hold_minutes is not None else 0.0
            self.symbol_table.setItem(row_idx, 17, QTableWidgetItem(f"{hold:.1f}"))
            self.symbol_table.setItem(row_idx, 18, QTableWidgetItem(self._recent_unit_history(units, perf.code)))
        self.symbol_table.resizeColumnsToContents()

        if not units:
            self.summary_label.setText("체결 데이터 없음(기간/모드/체잔 저장 확인)")
        else:
            best = daily.best_trade
            worst = daily.worst_trade
            self.summary_label.setText(
                " | ".join(
                    [
                        f"기간 {self.start_date.date().toString('yyyy-MM-dd')}~{self.end_date.date().toString('yyyy-MM-dd')}",
                        f"거래수 {daily.total_trades}",
                        f"성공/실패 {daily.wins}/{daily.losses} ({daily.win_rate:.1f}%)",
                        f"실현손익(세전) {daily.gross_pnl_sum:,}",
                        f"수수료 {daily.fee_sum:,} / 세금 {daily.tax_sum:,}",
                        f"실현손익(세후) {daily.net_pnl_sum:,}",
                        f"평균손익/거래 {daily.avg_pnl:.2f}",
                        f"최대이익 {best.code if best else '-'} {best.net_pnl if best else 0}",
                        f"최대손실 {worst.code if worst else '-'} {worst.net_pnl if worst else 0}",
                        f"베스트 {daily.best_symbol or '-'} / 워스트 {daily.worst_symbol or '-'}",
                    ]
                )
            )

        self.bucket_table.setRowCount(len(daily.time_bucket_perf) if daily else 0)
        for idx, bucket in enumerate(daily.time_bucket_perf if daily else []):
            self.bucket_table.setItem(idx, 0, QTableWidgetItem(bucket["bucket"]))
            self.bucket_table.setItem(idx, 1, QTableWidgetItem(str(bucket["trades"])))
            self.bucket_table.setItem(idx, 2, QTableWidgetItem(f"{bucket['win_rate']:.1f}"))
            self.bucket_table.setItem(idx, 3, QTableWidgetItem(f"{bucket['net_pnl']:,}"))
        self.bucket_table.resizeColumnsToContents()

        top_sorted = sorted(symbol_perf, key=lambda x: x.net_pnl_sum, reverse=True)[:10]
        bottom_sorted = sorted(symbol_perf, key=lambda x: x.net_pnl_sum)[:10]
        self._fill_rank_table(self.top_table, top_sorted)
        self._fill_rank_table(self.bottom_table, bottom_sorted)

    def _save_snapshot(
        self,
        start_dt,
        end_dt,
        mode,
        winloss_mode,
        fills,
        units,
        symbol_perf,
        daily,
    ) -> None:
        try:
            ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            snap_path = self.reports_dir / "snapshots" / f"report_{ts}.json"
            payload = {
                "ts": ts,
                "period": {"start": start_dt.isoformat(), "end": end_dt.isoformat()},
                "mode": mode,
                "winloss_mode": winloss_mode,
                "counts": {
                    "fills": len(fills),
                    "units": len(units),
                    "symbols": len(symbol_perf) if symbol_perf else 0,
                },
                "summary": {
                    "net_pnl_sum": getattr(daily, "net_pnl_sum", 0) if daily else 0,
                    "gross_pnl_sum": getattr(daily, "gross_pnl_sum", 0) if daily else 0,
                    "wins": getattr(daily, "wins", 0) if daily else 0,
                    "losses": getattr(daily, "losses", 0) if daily else 0,
                    "win_rate": getattr(daily, "win_rate", 0) if daily else 0,
                },
                "symbol_perf_top": [
                    {
                        "code": p.code,
                        "name": self._resolve_name(p.code, p.name),
                        "trades": p.trades,
                        "wins": p.wins,
                        "losses": p.losses,
                        "win_rate": p.win_rate,
                        "net_pnl_sum": p.net_pnl_sum,
                        "return_pct": p.return_pct,
                    }
                    for p in (symbol_perf[:200] if symbol_perf else [])
                ],
            }
            from .persistence import save_json
            from .app_paths import reports_last_path

            save_json(snap_path, payload)
            save_json(reports_last_path(self.reports_dir.parent), payload)
            self.status_label.setText(self.status_label.text() + " / 스냅샷 저장됨")
        except Exception as exc:
            try:
                self.status_label.setText(self.status_label.text() + f" / 스냅샷 저장 실패: {exc}")
            except Exception:
                pass

    def _fill_rank_table(self, table: QTableWidget, rows) -> None:
        table.setRowCount(len(rows))
        for idx, perf in enumerate(rows):
            table.setItem(idx, 0, QTableWidgetItem(perf.code))
            table.setItem(idx, 1, QTableWidgetItem(self._resolve_name(perf.code, perf.name)))
            table.setItem(idx, 2, QTableWidgetItem(str(perf.trades)))
            table.setItem(idx, 3, QTableWidgetItem(f"{perf.win_rate:.2f}"))
            self._set_signed_item(table, idx, 4, float(perf.net_pnl_sum), "{:+,.0f}")
        table.resizeColumnsToContents()

    def _export_symbol_csv(self) -> None:
        if not self._last_symbol_perf:
            self.status_label.setText("내보낼 종목성과 데이터가 없습니다.")
            return
        filename = f"catch_like_symbol_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        default_dir = str(self.reports_dir / "exports")
        path_str, _ = QFileDialog.getSaveFileName(
            self, "종목성과 CSV 저장", str(Path(default_dir) / filename), "CSV Files (*.csv)"
        )
        if not path_str:
            return
        rows = []
        for perf in self._last_symbol_perf:
            rows.append(
                {
                    "종목코드": perf.code,
                    "종목명": self._resolve_name(perf.code, perf.name),
                    "거래수": perf.trades,
                    "성공": perf.wins,
                    "실패": perf.losses,
                    "성공률(%)": round(perf.win_rate, 2),
                    "매수금액": perf.buy_amount,
                    "매도금액": perf.sell_amount,
                    "실현손익(세전)": perf.gross_profit_sum + perf.gross_loss_sum,
                    "수수료": perf.fee_sum,
                    "세금": perf.tax_sum,
                    "실현손익(세후)": perf.net_pnl_sum,
                    "수익률(%)": round(perf.return_pct, 2),
                    "평균손익": round(perf.avg_pnl, 2),
                    "평균성공": round(perf.avg_win, 2),
                    "평균실패": round(perf.avg_loss, 2),
                    "PF": round(perf.profit_factor, 2),
                    "평균보유(분)": round(perf.avg_hold_minutes or 0, 2),
                    "최근거래이력": self._recent_unit_history(self._last_units, perf.code),
                }
            )
        self._write_csv(Path(path_str), rows, meta=f"기간={self.start_date.text()}~{self.end_date.text()} 모드={self.mode_combo.currentText()} 승패={self.winloss_combo.currentText()}")

    def _export_daily_csv(self) -> None:
        if not self._last_daily:
            self.status_label.setText("내보낼 보고서 데이터가 없습니다.")
            return
        filename = f"catch_like_daily_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        default_dir = str(self.reports_dir / "exports")
        path_str, _ = QFileDialog.getSaveFileName(
            self, "당일 보고서 CSV 저장", str(Path(default_dir) / filename), "CSV Files (*.csv)"
        )
        if not path_str:
            return
        daily = self._last_daily
        rows = []
        meta = (
            f"기간={self.start_date.text()}~{self.end_date.text()} "
            f"모드={self.mode_combo.currentText()} 승패={self.winloss_combo.currentText()}"
        )
        rows.append({"KPI": "총거래", "값": daily.total_trades})
        rows.append({"KPI": "성공/실패", "값": f"{daily.wins}/{daily.losses} ({daily.win_rate:.1f}%)"})
        rows.append({"KPI": "실현손익(세전)", "값": daily.gross_pnl_sum})
        rows.append({"KPI": "수수료/세금", "값": f"{daily.fee_sum}/{daily.tax_sum}"})
        rows.append({"KPI": "실현손익(세후)", "값": daily.net_pnl_sum})
        rows.append({"KPI": "평균손익/거래", "값": round(daily.avg_pnl, 2)})
        rows.append({})
        rows.append({"시간대": "시간대", "거래수": "거래수", "성공률": "성공률(%)", "순손익": "실현손익(세후)"})
        for bucket in daily.time_bucket_perf:
            rows.append(
                {
                    "시간대": bucket["bucket"],
                    "거래수": bucket["trades"],
                    "성공률": round(bucket["win_rate"], 1),
                    "순손익": bucket["net_pnl"],
                }
            )
        rows.append({})
        rows.append({"Top": "상위 종목"})
        for perf in sorted(self._last_symbol_perf, key=lambda x: x.net_pnl_sum, reverse=True)[:10]:
            rows.append(
                {
                    "종목코드": perf.code,
                    "종목명": self._resolve_name(perf.code, perf.name),
                    "거래수": perf.trades,
                    "성공률": round(perf.win_rate, 2),
                    "실현손익(세후)": perf.net_pnl_sum,
                }
            )
        rows.append({})
        rows.append({"Bottom": "하위 종목"})
        for perf in sorted(self._last_symbol_perf, key=lambda x: x.net_pnl_sum)[:10]:
            rows.append(
                {
                    "종목코드": perf.code,
                    "종목명": self._resolve_name(perf.code, perf.name),
                    "거래수": perf.trades,
                    "성공률": round(perf.win_rate, 2),
                    "실현손익(세후)": perf.net_pnl_sum,
                }
            )
        self._write_csv(Path(path_str), rows, meta=meta)

    @staticmethod
    def _write_csv(path: Path, rows: list[dict], meta: Optional[str]) -> None:
        if not rows:
            path.write_text("", encoding="utf-8")
            return
        with path.open("w", newline="", encoding="utf-8") as handle:
            # rows는 섹션별로 컬럼이 달라질 수 있으므로, 모든 키의 합집합으로 header 구성
            fieldnames: list[str] = []
            seen: set[str] = set()
            for r in rows:
                for k in r.keys():
                    if k not in seen:
                        fieldnames.append(k)
                        seen.add(k)

            if not fieldnames:
                return

            if meta:
                handle.write(f"# {meta}\n")
            writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            for row in rows:
                writer.writerow(row)
