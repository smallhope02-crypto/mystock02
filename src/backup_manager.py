from __future__ import annotations

import datetime as _dt
import json
import logging
import shutil
import time
import zipfile
from pathlib import Path
from typing import Optional

from .persistence import save_json

logger = logging.getLogger(__name__)


class BackupManager:
    def __init__(self, data_dir: Path, keep_last: int = 30, mode: str = "zip") -> None:
        self.data_dir = data_dir
        self.keep_last = keep_last
        self.mode = mode
        self.last_backup_ts: Optional[str] = None
        self.last_backup_ok: bool | None = None
        self.last_backup_dir: Optional[Path] = None
        self.last_backup_count: int = 0
        self.last_backup_error: str = ""

    def _stamp(self) -> str:
        return _dt.datetime.now().strftime("%Y%m%d_%H%M%S")

    def _backup_root(self) -> Path:
        return self.data_dir / "backups"

    def _zip_add_dir(self, zf: zipfile.ZipFile, src_dir: Path, arc_base: str) -> int:
        count = 0
        if not src_dir.exists():
            return 0
        for path in src_dir.rglob("*"):
            if path.is_file():
                rel = f"{arc_base}/{path.relative_to(src_dir).as_posix()}"
                zf.write(path, rel)
                count += 1
        return count

    def run_backup(self, reason: str = "manual") -> Path:
        start = time.perf_counter()
        ts = self._stamp()
        out_dir = self._backup_root()
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"backup_{ts}"
        if self.mode == "zip":
            out_path = out_dir / f"backup_{ts}.zip"
        else:
            out_path.mkdir(parents=True, exist_ok=True)

        logger.info("[BACKUP] start reason=%s out=%s mode=%s", reason, out_path, self.mode)

        copied_count = 0
        failed_files: list[str] = []
        failed_dirs: list[str] = []
        error_message = ""

        def _count_files(path: Path) -> int:
            if not path.exists():
                return 0
            return sum(1 for p in path.rglob("*") if p.is_file())

        file_targets = [
            (self.data_dir / "config" / "settings.ini", "config/settings.ini"),
            (self.data_dir / "trade" / "trade_history.db", "trade/trade_history.db"),
            (self.data_dir / "trade" / "trade_history.db-wal", "trade/trade_history.db-wal"),
            (self.data_dir / "trade" / "trade_history.db-shm", "trade/trade_history.db-shm"),
            (self.data_dir / "monitor" / "monitor_snapshot.json", "monitor/monitor_snapshot.json"),
            (self.data_dir / "reports" / "last_report.json", "reports/last_report.json"),
        ]

        dir_targets = [
            (self.data_dir / "logs", "logs"),
            (self.data_dir / "reports" / "snapshots", "reports/snapshots"),
            (self.data_dir / "reports" / "exports", "reports/exports"),
            (self.data_dir / "opportunity", "opportunity"),
        ]

        if self.mode == "zip":
            try:
                with zipfile.ZipFile(out_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                    for src, arc in file_targets:
                        if not src.exists():
                            continue
                        zf.write(src, arc)
                        copied_count += 1
                    for src, arc in dir_targets:
                        copied_count += self._zip_add_dir(zf, src, arc)
            except Exception as exc:  # pragma: no cover - filesystem dependent
                error_message = f"zip backup failed: {exc}"
                failed_dirs.append(error_message)
        else:
            for src, arc in file_targets:
                if not src.exists():
                    continue
                dst = out_path / arc
                try:
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, dst)
                    copied_count += 1
                except Exception as exc:  # pragma: no cover - filesystem dependent
                    failed_files.append(f"{src} -> {dst} ({exc})")

            for src, arc in dir_targets:
                if not src.exists():
                    continue
                dst = out_path / arc
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
        if self.mode == "zip":
            save_json(out_dir / "backup_meta.json", meta)
            save_json(out_dir / f"backup_{ts}.meta.json", meta)
            try:
                with zipfile.ZipFile(out_path, "a", compression=zipfile.ZIP_DEFLATED) as zf:
                    zf.writestr("backup_meta.json", json.dumps(meta, ensure_ascii=False, indent=2))
            except Exception:  # pragma: no cover - filesystem dependent
                pass
        else:
            save_json(out_path / "backup_meta.json", meta)

        self.last_backup_ts = ts
        self.last_backup_ok = ok
        self.last_backup_dir = out_path
        self.last_backup_count = copied_count
        self.last_backup_error = error_message
        self._rotate_backups()

        logger.info(
            "[BACKUP] end ok=%s count=%s dur_ms=%s out=%s",
            ok,
            copied_count,
            duration_ms,
            out_path,
        )
        return out_path

    def _rotate_backups(self) -> None:
        root = self._backup_root()
        if not root.exists():
            return
        items = [
            p
            for p in root.iterdir()
            if (p.is_dir() and p.name.startswith("backup_"))
            or (p.is_file() and p.name.startswith("backup_") and p.suffix == ".zip")
        ]
        items.sort(key=lambda p: p.name, reverse=True)
        for p in items[self.keep_last :]:
            try:
                if p.is_dir():
                    shutil.rmtree(p, ignore_errors=True)
                else:
                    p.unlink(missing_ok=True)
                    meta_path = p.with_suffix(".meta.json")
                    if meta_path.exists():
                        meta_path.unlink(missing_ok=True)
            except Exception:
                pass
