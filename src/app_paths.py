from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

try:
    from PyQt5.QtCore import QStandardPaths  # type: ignore
except Exception:
    try:
        from PyQt6.QtCore import QStandardPaths  # type: ignore
    except Exception:
        QStandardPaths = None  # type: ignore


APP_ORG = "Mystock02"
APP_NAME = "AutoTrader"


def _documents_dir_fallback() -> Path:
    home = Path.home()
    cand = home / "Documents"
    return cand if cand.exists() else home


def get_documents_dir() -> Path:
    if QStandardPaths is not None:
        try:
            p = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation)  # type: ignore
            if p:
                return Path(p).expanduser().resolve()
        except Exception:
            pass
    return _documents_dir_fallback().resolve()


def get_default_data_dir() -> Path:
    return get_documents_dir() / "mystock02_data"


def resolve_data_dir(user_selected: Optional[str] = None) -> Path:
    env = os.getenv("MYSTOCK02_DATA_DIR", "").strip()
    if env:
        return Path(env).expanduser().resolve()
    if user_selected:
        s = str(user_selected).strip()
        if s:
            return Path(s).expanduser().resolve()
    return get_default_data_dir().resolve()


def ensure_data_dirs(data_dir: Path) -> None:
    (data_dir / "config").mkdir(parents=True, exist_ok=True)
    (data_dir / "logs").mkdir(parents=True, exist_ok=True)
    (data_dir / "trade").mkdir(parents=True, exist_ok=True)
    (data_dir / "monitor").mkdir(parents=True, exist_ok=True)
    (data_dir / "reports" / "snapshots").mkdir(parents=True, exist_ok=True)
    (data_dir / "reports" / "exports").mkdir(parents=True, exist_ok=True)
    (data_dir / "opportunity").mkdir(parents=True, exist_ok=True)
    (data_dir / "backups").mkdir(parents=True, exist_ok=True)


def settings_ini_path(data_dir: Path) -> Path:
    return data_dir / "config" / "settings.ini"


def trade_db_path(data_dir: Path) -> Path:
    return data_dir / "trade" / "trade_history.db"


def app_log_path(data_dir: Path) -> Path:
    return data_dir / "logs" / "app.log"


def condition_log_path(data_dir: Path) -> Path:
    return data_dir / "logs" / "condition.log"


def monitor_snapshot_path(data_dir: Path) -> Path:
    return data_dir / "monitor" / "monitor_snapshot.json"


def reports_dir(data_dir: Path) -> Path:
    return data_dir / "reports"


def reports_last_path(data_dir: Path) -> Path:
    return data_dir / "reports" / "last_report.json"


def backups_dir(data_dir: Path) -> Path:
    return data_dir / "backups"
