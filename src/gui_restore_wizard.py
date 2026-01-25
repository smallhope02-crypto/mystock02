from __future__ import annotations

import json
import logging
import sqlite3
import shutil
from pathlib import Path
from typing import Optional

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QCheckBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)

from .persistence import save_json

logger = logging.getLogger(__name__)


class RestoreWizard(QDialog):
    restored = pyqtSignal(dict)

    def __init__(self, parent=None, current_data_dir: Path | str = "", secure_settings=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("복원 마법사")
        self.current_data_dir = Path(current_data_dir)
        self.secure_settings = secure_settings
        self.source_dir: Optional[Path] = None
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout()

        header = QHBoxLayout()
        self.source_label = QLabel("소스: -")
        self.choose_btn = QPushButton("복원 소스 선택...")
        self.scan_btn = QPushButton("스캔")
        self.restore_btn = QPushButton("복원 실행")
        header.addWidget(self.source_label)
        header.addStretch(1)
        header.addWidget(self.choose_btn)
        header.addWidget(self.scan_btn)
        header.addWidget(self.restore_btn)
        layout.addLayout(header)

        self.backup_before_restore = QCheckBox("복원 전 현재 data_dir 1회 백업")
        self.backup_before_restore.setChecked(True)
        layout.addWidget(self.backup_before_restore)

        self.items_list = QListWidget()
        layout.addWidget(self.items_list)

        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMinimumHeight(120)
        layout.addWidget(self.log_view)

        self.setLayout(layout)

        self.choose_btn.clicked.connect(self._choose_source)
        self.scan_btn.clicked.connect(self._scan_source)
        self.restore_btn.clicked.connect(self._restore)

    def _log(self, message: str) -> None:
        self.log_view.append(message)
        logger.info(message)

    def _choose_source(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "복원 소스 선택", str(self.current_data_dir))
        if not path:
            return
        self.source_dir = Path(path)
        self.source_label.setText(f"소스: {self.source_dir}")
        self._log(f"[RESTORE] source selected: {self.source_dir}")

    def _scan_source(self) -> None:
        if not self.source_dir:
            self._log("[RESTORE] 소스를 먼저 선택하세요.")
            return
        self.items_list.clear()
        found = self._scan_items(self.source_dir)
        for item in found:
            self.items_list.addItem(item)
        self._log(f"[RESTORE] scan 완료: items={len(found)}")

    def _scan_items(self, source_dir: Path) -> list[str]:
        items = []
        candidates = self._source_candidates(source_dir)
        for label, src in candidates.items():
            if src.exists():
                items.append(f"{label}: {src}")
        return items

    def _source_candidates(self, source_dir: Path) -> dict[str, Path]:
        direct = {
            "settings.ini": source_dir / "settings.ini",
            "trade_history.db": source_dir / "trade_history.db",
            "logs": source_dir / "logs",
            "monitor_snapshot.json": source_dir / "monitor_snapshot.json",
            "reports": source_dir / "reports",
            "opportunity": source_dir / "opportunity",
        }
        nested = {
            "settings.ini": source_dir / "config" / "settings.ini",
            "trade_history.db": source_dir / "trade" / "trade_history.db",
            "logs": source_dir / "logs",
            "monitor_snapshot.json": source_dir / "monitor" / "monitor_snapshot.json",
            "reports": source_dir / "reports",
            "opportunity": source_dir / "opportunity",
        }
        return nested if (source_dir / "config").exists() else direct

    def _restore(self) -> None:
        if not self.source_dir:
            self._log("[RESTORE] 소스를 먼저 선택하세요.")
            return

        self._log("[RESTORE] restore start")
        errors: list[str] = []
        copied_files = 0

        candidates = self._source_candidates(self.source_dir)
        target = self.current_data_dir

        mapping = {
            "settings.ini": target / "config" / "settings.ini",
            "trade_history.db": target / "trade" / "trade_history.db",
            "logs": target / "logs",
            "monitor_snapshot.json": target / "monitor" / "monitor_snapshot.json",
            "reports": target / "reports",
            "opportunity": target / "opportunity",
        }

        for key, src in candidates.items():
            if not src.exists():
                continue
            dst = mapping[key]
            try:
                if src.is_dir():
                    shutil.copytree(src, dst, dirs_exist_ok=True)
                    copied_files += sum(1 for p in dst.rglob("*") if p.is_file())
                else:
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, dst)
                    copied_files += 1
            except Exception as exc:  # pragma: no cover - filesystem dependent
                errors.append(f"{src} -> {dst}: {exc}")

        verify = self._verify_target(target)
        payload = {
            "ok": not errors and verify["ok"],
            "copied_files": copied_files,
            "errors": errors,
            "source_dir": str(self.source_dir),
            "verify": verify,
        }

        self._log(f"[RESTORE] restore end ok={payload['ok']} files={copied_files}")
        if errors:
            self._log(f"[RESTORE] errors={errors}")
        self.restored.emit(payload)

    def _verify_target(self, target: Path) -> dict:
        result = {"ok": True, "checks": {}}
        settings = target / "config" / "settings.ini"
        result["checks"]["settings.ini"] = settings.exists()
        if not settings.exists():
            result["ok"] = False

        db_path = target / "trade" / "trade_history.db"
        result["checks"]["trade_history.db"] = db_path.exists()
        if db_path.exists():
            try:
                sqlite3.connect(db_path).close()
            except Exception:
                result["ok"] = False
        else:
            result["ok"] = False

        last_report = target / "reports" / "last_report.json"
        if last_report.exists():
            try:
                json.loads(last_report.read_text(encoding="utf-8"))
                result["checks"]["last_report.json"] = True
            except Exception:
                result["checks"]["last_report.json"] = False
        else:
            result["checks"]["last_report.json"] = False

        monitor_snapshot = target / "monitor" / "monitor_snapshot.json"
        if monitor_snapshot.exists():
            try:
                json.loads(monitor_snapshot.read_text(encoding="utf-8"))
                result["checks"]["monitor_snapshot.json"] = True
            except Exception:
                result["checks"]["monitor_snapshot.json"] = False
        else:
            result["checks"]["monitor_snapshot.json"] = False

        save_json(target / "backups" / "last_restore.json", result)
        return result
