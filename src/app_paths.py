from __future__ import annotations

from pathlib import Path


def get_repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def get_data_dir() -> Path:
    return get_repo_root() / "mystock02_data"


def ensure_data_dirs() -> Path:
    data_dir = get_data_dir()
    (data_dir / "logs").mkdir(parents=True, exist_ok=True)
    (data_dir / "trade").mkdir(parents=True, exist_ok=True)
    (data_dir / "reports" / "snapshots").mkdir(parents=True, exist_ok=True)
    (data_dir / "reports" / "exports").mkdir(parents=True, exist_ok=True)
    (data_dir / "opportunity").mkdir(parents=True, exist_ok=True)
    return data_dir


def get_logs_dir() -> Path:
    return get_data_dir() / "logs"


def get_trade_db_path() -> Path:
    return get_data_dir() / "trade" / "trade_history.db"


def get_settings_ini_path() -> Path:
    return get_data_dir() / "settings.ini"


def get_monitor_snapshot_path() -> Path:
    return get_data_dir() / "monitor_snapshot.json"


def get_reports_dir() -> Path:
    return get_data_dir() / "reports"


def get_reports_last_path() -> Path:
    return get_reports_dir() / "last_report.json"


def get_opportunity_dir() -> Path:
    return get_data_dir() / "opportunity"
