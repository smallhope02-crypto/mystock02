"""Track missed strong candidates and evaluate lookahead returns."""

from __future__ import annotations

import csv
import datetime
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional

from .scanner import ScanResult

logger = logging.getLogger(__name__)


@dataclass
class MissedCandidate:
    ts_scan: datetime.datetime
    code: str
    desired_rank: int
    score: float
    trade_value: float
    change_rate: float
    event_score: float
    reason: str
    current_price_at_scan: Optional[float]
    vwap_at_scan: Optional[float]
    intraday_high_at_scan: Optional[float]
    meta_json: str
    pending_lookaheads: List[int] = field(default_factory=list)


@dataclass
class OpportunityEval:
    ts_scan: datetime.datetime
    code: str
    reason: str
    score: float
    price_at_scan: float
    ts_eval: datetime.datetime
    lookahead_min: int
    price_eval: float
    return_pct: float


class MissedOpportunityTracker:
    def __init__(
        self,
        logs_dir: Path,
        lookahead_minutes: Optional[List[int]] = None,
        max_records: int = 5000,
        max_age_days: int = 7,
    ) -> None:
        self.logs_dir = logs_dir
        self.lookahead_minutes = lookahead_minutes or [5, 15, 30]
        self.max_records = max_records
        self.max_age_days = max_age_days
        self._records: List[MissedCandidate] = []
        self._eval_records: List[OpportunityEval] = []
        self._missed_path = self.logs_dir / "missed_candidates.csv"
        self._eval_path = self.logs_dir / "missed_opportunity_eval.csv"

    def record_missed(
        self,
        scan_result: ScanResult,
        price_snapshot: Dict[str, Optional[float]],
        log_fn: Optional[Callable[[str], None]] = None,
    ) -> None:
        missed = scan_result.missed_new_strong
        if not missed:
            return

        self.logs_dir.mkdir(parents=True, exist_ok=True)
        for code in missed:
            record = MissedCandidate(
                ts_scan=scan_result.ts_scan,
                code=code,
                desired_rank=scan_result.ranks.get(code, 0),
                score=scan_result.scores.get(code, 0.0),
                trade_value=scan_result.trade_value.get(code, 0.0),
                change_rate=scan_result.change_rate.get(code, 0.0),
                event_score=scan_result.event_score.get(code, 0.0),
                reason=scan_result.reason_map.get(code, "other"),
                current_price_at_scan=price_snapshot.get(code),
                vwap_at_scan=scan_result.vwap.get(code),
                intraday_high_at_scan=scan_result.intraday_high.get(code),
                meta_json=json.dumps(
                    {"source": "scanner"}, ensure_ascii=False
                ),
                pending_lookaheads=list(self.lookahead_minutes),
            )
            self._records.append(record)
            self._append_missed_csv(record)
            if log_fn:
                log_fn(
                    f"[MISSED_DETAIL] code={record.code} rank={record.desired_rank} score={record.score:.4f} "
                    f"reason={record.reason} price={record.current_price_at_scan}"
                )

        examples = ",".join(missed[:5])
        if log_fn:
            log_fn(
                f"[MISSED] strong_new={len(missed)} total_missed={len(scan_result.desired_universe) - len(scan_result.applied_universe)} examples=[{examples}]"
            )

        self._prune_records()

    def evaluate_pending(
        self,
        get_price_fn: Callable[[str], Optional[float]],
        now: Optional[datetime.datetime] = None,
        log_fn: Optional[Callable[[str], None]] = None,
    ) -> None:
        if not self._records:
            return
        now = now or datetime.datetime.now()
        for record in list(self._records):
            if not record.pending_lookaheads:
                continue
            for lookahead_min in list(record.pending_lookaheads):
                if now < record.ts_scan + datetime.timedelta(minutes=lookahead_min):
                    continue
                try:
                    price_now = get_price_fn(record.code)
                except Exception as exc:  # pragma: no cover - defensive
                    price_now = None
                    if log_fn:
                        log_fn(f"[OPPORTUNITY] price_fetch_failed code={record.code} err={exc}")
                if price_now is None or record.current_price_at_scan in (None, 0):
                    if log_fn:
                        log_fn(f"[OPPORTUNITY] price_fetch_failed code={record.code}")
                    continue
                ret = (price_now - record.current_price_at_scan) / record.current_price_at_scan * 100
                eval_record = OpportunityEval(
                    ts_scan=record.ts_scan,
                    code=record.code,
                    reason=record.reason,
                    score=record.score,
                    price_at_scan=record.current_price_at_scan,
                    ts_eval=now,
                    lookahead_min=lookahead_min,
                    price_eval=price_now,
                    return_pct=ret,
                )
                self._eval_records.append(eval_record)
                self._append_eval_csv(eval_record)
                record.pending_lookaheads.remove(lookahead_min)
                if log_fn:
                    log_fn(
                        f"[OPPORTUNITY_EVAL] code={record.code} lookahead={lookahead_min}m "
                        f"ret={ret:.2f}% price0={record.current_price_at_scan} price1={price_now}"
                    )

        self._prune_records()
        self._prune_eval_records()

    def summarize(self, window_minutes: int = 60, now: Optional[datetime.datetime] = None) -> Dict[str, float]:
        now = now or datetime.datetime.now()
        window_start = now - datetime.timedelta(minutes=window_minutes)
        recent = [r for r in self._eval_records if r.ts_eval >= window_start]
        summary: Dict[str, float] = {"missed_strong": float(len(recent))}
        if not recent:
            return summary
        for lookahead in sorted(set(r.lookahead_min for r in recent)):
            vals = [r.return_pct for r in recent if r.lookahead_min == lookahead]
            if not vals:
                continue
            avg = sum(vals) / len(vals)
            pos_ratio = sum(1 for v in vals if v > 0) / len(vals) * 100
            summary[f"avg_{lookahead}m"] = avg
            summary[f"pos_{lookahead}m"] = pos_ratio
        return summary

    def _append_missed_csv(self, record: MissedCandidate) -> None:
        header = [
            "ts_scan",
            "code",
            "desired_rank",
            "score",
            "trade_value",
            "change_rate",
            "event_score",
            "reason",
            "current_price_at_scan",
            "vwap_at_scan",
            "intraday_high_at_scan",
            "meta_json",
        ]
        row = [
            record.ts_scan.isoformat(),
            record.code,
            record.desired_rank,
            f"{record.score:.6f}",
            record.trade_value,
            record.change_rate,
            record.event_score,
            record.reason,
            record.current_price_at_scan or "",
            record.vwap_at_scan or "",
            record.intraday_high_at_scan or "",
            record.meta_json,
        ]
        self._append_csv(self._missed_path, header, row)

    def _append_eval_csv(self, record: OpportunityEval) -> None:
        header = [
            "ts_scan",
            "code",
            "reason",
            "score",
            "price_at_scan",
            "ts_eval",
            "lookahead_min",
            "price_eval",
            "return_pct",
        ]
        row = [
            record.ts_scan.isoformat(),
            record.code,
            record.reason,
            f"{record.score:.6f}",
            record.price_at_scan,
            record.ts_eval.isoformat(),
            record.lookahead_min,
            record.price_eval,
            f"{record.return_pct:.6f}",
        ]
        self._append_csv(self._eval_path, header, row)

    def _append_csv(self, path: Path, header: List[str], row: Iterable[object]) -> None:
        exists = path.exists()
        with path.open("a", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            if not exists:
                writer.writerow(header)
            writer.writerow(row)

    def _prune_records(self) -> None:
        if not self._records:
            return
        cutoff = datetime.datetime.now() - datetime.timedelta(days=self.max_age_days)
        self._records = [r for r in self._records if r.ts_scan >= cutoff]
        if len(self._records) > self.max_records:
            self._records = self._records[-self.max_records :]

    def _prune_eval_records(self) -> None:
        if not self._eval_records:
            return
        cutoff = datetime.datetime.now() - datetime.timedelta(days=self.max_age_days)
        self._eval_records = [r for r in self._eval_records if r.ts_eval >= cutoff]
