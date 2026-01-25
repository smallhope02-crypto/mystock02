from __future__ import annotations

import datetime as _dt
import shutil
from pathlib import Path
from typing import Optional

from .persistence import save_json


class BackupManager:
    def __init__(self, data_dir: Path, keep_last: int = 30) -> None:
        self.data_dir = data_dir
        self.keep_last = keep_last
        self.last_backup_ts: Optional[str] = None

    def _stamp(self) -> str:
        return _dt.datetime.now().strftime("%Y%m%d_%H%M%S")

    def _backup_root(self) -> Path:
        return self.data_dir / "backups"

    def run_backup(self, reason: str = "manual") -> Path:
        ts = self._stamp()
        out_dir = self._backup_root() / f"backup_{ts}"
        out_dir.mkdir(parents=True, exist_ok=True)

        targets = [
            (self.data_dir / "config" / "settings.ini", out_dir / "settings.ini"),
            (self.data_dir / "trade" / "trade_history.db", out_dir / "trade_history.db"),
            (self.data_dir / "logs" / "app.log", out_dir / "app.log"),
            (self.data_dir / "logs" / "condition.log", out_dir / "condition.log"),
            (self.data_dir / "monitor" / "monitor_snapshot.json", out_dir / "monitor_snapshot.json"),
            (self.data_dir / "reports" / "last_report.json", out_dir / "last_report.json"),
        ]
        copied = []
        for src, dst in targets:
            if src.exists():
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
                copied.append(dst.name)

        meta = {
            "ts": ts,
            "reason": reason,
            "copied": copied,
        }
        save_json(out_dir / "backup_meta.json", meta)

        self.last_backup_ts = ts
        self._rotate_backups()

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
