"""Condition event logger for Kiwoom OpenAPI condition flows."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Iterable

try:
    from PyQt5.QtCore import QSettings  # type: ignore
except Exception:  # pragma: no cover - fallback when Qt is unavailable
    QSettings = None  # type: ignore

from .app_paths import ensure_data_dirs, resolve_data_dir

_LOGGER: logging.Logger | None = None


def get_condition_logger() -> logging.Logger:
    """Return a rotating logger that writes to logs/condition.log."""

    global _LOGGER
    if _LOGGER is not None:
        return _LOGGER

    logger = logging.getLogger("condition_logger")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    if not logger.handlers:
        user_dir = ""
        if QSettings is not None:
            try:
                secure = QSettings("Mystock02", "AutoTrader")
                user_dir = secure.value("storage/data_dir", "")
            except Exception:
                user_dir = ""
        data_dir = resolve_data_dir(user_dir)
        ensure_data_dirs(data_dir)
        log_dir = data_dir / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / "condition.log"
        handler = RotatingFileHandler(
            log_path, maxBytes=10 * 1024 * 1024, backupCount=10, encoding="utf-8"
        )
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)

    _LOGGER = logger
    return logger


def _summarize_codes(codes: str | Iterable[str] | None) -> dict[str, Any]:
    if codes is None:
        return {}
    if isinstance(codes, str):
        parts = [c for c in codes.split(";") if c]
    else:
        parts = [str(c) for c in codes if c]
    head = parts[:10]
    return {
        "codeCount": len(parts),
        "codeHead": head,
    }


def condition_event(event: str, **fields: Any) -> None:
    """Log a condition event as JSONL with common fields."""

    try:
        payload: dict[str, Any] = {
            "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
            "event": event,
        }
        codes = fields.pop("codeList", None)
        if codes is not None:
            payload["codeList"] = codes
            payload.update(_summarize_codes(codes))
        payload.update(fields)
        line = json.dumps(payload, ensure_ascii=False)
        get_condition_logger().info(line)
        logging.getLogger("mystock02.condition").info(line)
    except Exception:
        # Logging must never break main flows.
        return
