from __future__ import annotations

import csv
import datetime as _dt
from pathlib import Path
from typing import Iterable


class BuyDecisionLogger:
    def __init__(self, csv_path: Path | str) -> None:
        self.csv_path = Path(csv_path)
        self.csv_path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, records: Iterable[dict]) -> None:
        rows = list(records or [])
        if not rows:
            return
        fieldnames = ["ts", "context", "symbol", "reason", "detail"]
        write_header = not self.csv_path.exists()
        with self.csv_path.open("a", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            if write_header:
                writer.writeheader()
            for row in rows:
                writer.writerow(
                    {
                        "ts": row.get("ts") or _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "context": row.get("context") or "",
                        "symbol": row.get("symbol") or "",
                        "reason": row.get("reason") or "",
                        "detail": row.get("detail") or "",
                    }
                )

    def read_recent(self, limit: int = 300) -> list[dict]:
        if not self.csv_path.exists():
            return []
        with self.csv_path.open("r", newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        if limit > 0:
            rows = rows[-limit:]
        return rows
