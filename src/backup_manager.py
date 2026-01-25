from __future__ import annotations

import datetime as _dt
import logging
import shutil
import time
from pathlib import Path
from typing import Optional

from .persistence import save_json

logger = logging.getLogger(__name__)


class BackupManager:
    def __init__(self, data_dir: Path, keep_last: int = 30) -> None:
        self.data_dir = data_dir
        self.keep_last = keep_last
        self.last_backup_ts: Optional[str] = None
        self.last_backup_ok: bool | None = None
        self.last_backup_dir: Optional[Path] = None
        self.last_backup_count: int = 0
        self.last_backup_error: str = ""

    def _stamp(self) -> str:
        return _dt.datetime.now().strftime("%Y%m%d_%H%M%S")

    def _backup_root(self) -> Path:
        return self.data_dir / "backups"

    def run_backup(self, reason: str = "manual") -> Path:
        start = time.perf_counter()
        ts = self._stamp()
        out_dir = self._backup_root() / f"backup_{ts}"
        out_dir.mkdir(parents=True, exist_ok=True)

        logger.info("[BACKUP] start reason=%s out=%s", reason, out_dir)

        copied_count = 0
        failed_files: list[str] = []
        failed_dirs: list[str] = []
        error_message = ""

        def _count_files(path: Path) -> int:
            if not path.exists():
                return 0
            return sum(1 for p in path.rglob("*") if p.is_file())

        file_targets = [
            (self.data_dir / "config" / "settings.ini", out_dir / "config" / "settings.ini"),
            (self.data_dir / "trade" / "trade_history.db", out_dir / "trade" / "trade_history.db"),
            (self.data_dir / "trade" / "trade_history.db-wal", out_dir / "trade" / "trade_history.db-wal"),
            (self.data_dir / "trade" / "trade_history.db-shm", out_dir / "trade" / "trade_history.db-shm"),
            (self.data_dir / "monitor" / "monitor_snapshot.json", out_dir / "monitor" / "monitor_snapshot.json"),
            (self.data_dir / "reports" / "last_report.json", out_dir / "reports" / "last_report.json"),
        ]

        dir_targets = [
            (self.data_dir / "logs", out_dir / "logs"),
            (self.data_dir / "reports" / "snapshots", out_dir / "reports" / "snapshots"),
            (self.data_dir / "reports" / "exports", out_dir / "reports" / "exports"),
            (self.data_dir / "opportunity", out_dir / "opportunity"),
        ]

        for src, dst in file_targets:
            if not src.exists():
                continue
            try:
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
                copied_count += 1
            except Exception as exc:  # pragma: no cover - filesystem dependent
                failed_files.append(f"{src} -> {dst} ({exc})")

        for src, dst in dir_targets:
            if not src.exists():
                continue
            try:
                shutil.copytree(src, dst, dirs_exist_ok=True)
                copied_count += _count_files(dst)
            except Exception as exc:  # pragma: no cover - filesystem dependent
                failed_dirs.append(f"{src} -> {dst} ({exc})")

        ok = not failed_files and not failed_dirs
        duration_ms = int((time.perf_counter() - start) * 1000)
        if not ok:
            error_message = "backup completed with failures"

        meta = {
            "ts": ts,
            "reason": reason,
            "ok": ok,
            "copied_count": copied_count,
            "failed_files": failed_files,
            "failed_dirs": failed_dirs,
            "error_message": error_message,
            "duration_ms": duration_ms,
        }
        save_json(out_dir / "backup_meta.json", meta)

        self.last_backup_ts = ts
        self.last_backup_ok = ok
        self.last_backup_dir = out_dir
        self.last_backup_count = copied_count
        self.last_backup_error = error_message
        self._rotate_backups()

        logger.info(
            "[BACKUP] end ok=%s count=%s dur_ms=%s out=%s",
            ok,
            copied_count,
            duration_ms,
            out_dir,
        )
        return out_dir

    def _rotate_backups(self) -> None:
        root = self._backup_root()
        if not root.exists():
            return
        dirs = [p for p in root.iterdir() if p.is_dir() and p.name.startswith("backup_")]
        dirs.sort(key=lambda p: p.name, reverse=True)
        for p in dirs[self.keep_last :]:
            try:
                shutil.rmtree(p, ignore_errors=True)
            except Exception:
                pass
