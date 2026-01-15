"""Scanner mode universe churn control and override logic."""

from __future__ import annotations

import datetime
import logging
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Sequence

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ScannerConfig:
    max_watch: int = 100
    max_replacements_per_scan: int = 20
    override_margin: float = 0.2
    override_max_extra: int = 10
    incumbent_bonus: float = 0.1
    strong_rank_cutoff: int = 30
    strong_topk: int = 30


@dataclass
class ScanResult:
    ts_scan: datetime.datetime
    raw_count: int
    filtered_count: int
    desired_universe: List[str]
    applied_universe: List[str]
    current_universe: List[str]
    scores: Dict[str, float]
    ranks: Dict[str, int]
    to_add: List[str]
    to_remove: List[str]
    desired_swaps: int
    allowed_swaps: int
    override_extra: int
    applied_swaps: int
    override_triggered: bool
    missed_new_strong: List[str] = field(default_factory=list)
    reason_map: Dict[str, str] = field(default_factory=dict)
    trade_value: Dict[str, float] = field(default_factory=dict)
    change_rate: Dict[str, float] = field(default_factory=dict)
    event_score: Dict[str, float] = field(default_factory=dict)
    vwap: Dict[str, float] = field(default_factory=dict)
    intraday_high: Dict[str, float] = field(default_factory=dict)


class ScannerEngine:
    """Build desired/applied universes with churn control and override."""

    def __init__(
        self,
        score_fn: Callable[[Sequence[str]], Dict[str, float]],
        config: Optional[ScannerConfig] = None,
    ) -> None:
        self.score_fn = score_fn
        self.config = config or ScannerConfig()

    def scan(
        self,
        candidates: Sequence[str],
        current_universe: Sequence[str],
        trade_value: Optional[Dict[str, float]] = None,
        change_rate: Optional[Dict[str, float]] = None,
        event_score: Optional[Dict[str, float]] = None,
        vwap: Optional[Dict[str, float]] = None,
        intraday_high: Optional[Dict[str, float]] = None,
    ) -> ScanResult:
        ts_scan = datetime.datetime.now()
        raw = list(dict.fromkeys([c for c in candidates if c]))
        raw_count = len(raw)
        filtered = raw
        filtered_count = len(filtered)

        scores = self.score_fn(filtered) if filtered else {}
        scores = {k: float(v) for k, v in scores.items()}

        current = list(dict.fromkeys([c for c in current_universe if c]))
        current_set = set(current)
        desired_scores = {
            symbol: scores.get(symbol, 0.0) + (self.config.incumbent_bonus if symbol in current_set else 0.0)
            for symbol in filtered
        }
        ranked = sorted(desired_scores.items(), key=lambda kv: kv[1], reverse=True)
        desired = [symbol for symbol, _ in ranked[: self.config.max_watch]]
        ranks = {symbol: idx + 1 for idx, symbol in enumerate(desired)}

        desired_set = set(desired)
        to_add = [s for s in desired if s not in current_set]
        to_remove = [s for s in current if s not in desired_set]

        slots_available = max(0, self.config.max_watch - len(current))
        free_adds = to_add[:slots_available]
        remaining_adds = to_add[slots_available:]

        replacements_needed = max(0, len(remaining_adds))
        allowed_swaps = min(self.config.max_replacements_per_scan, replacements_needed, len(to_remove))
        removal_candidates = sorted(
            to_remove, key=lambda s: desired_scores.get(s, scores.get(s, 0.0))
        )
        removed = removal_candidates[:allowed_swaps]

        added = free_adds + sorted(
            remaining_adds, key=lambda s: desired_scores.get(s, scores.get(s, 0.0)), reverse=True
        )[:allowed_swaps]

        remaining_adds_after = [s for s in remaining_adds if s not in added]
        remaining_removals = [s for s in removal_candidates if s not in removed]

        worst_incumbent_score = None
        if current:
            incumbent_scores = [
                desired_scores.get(s, scores.get(s, 0.0)) for s in current if s not in removed
            ]
            if incumbent_scores:
                worst_incumbent_score = min(incumbent_scores)

        override_candidates = []
        if worst_incumbent_score is not None:
            for symbol in remaining_adds_after:
                if desired_scores.get(symbol, scores.get(symbol, 0.0)) >= worst_incumbent_score + self.config.override_margin:
                    override_candidates.append(symbol)
        override_candidates = sorted(
            override_candidates, key=lambda s: desired_scores.get(s, scores.get(s, 0.0)), reverse=True
        )
        override_extra = min(len(override_candidates), self.config.override_max_extra, len(remaining_removals))
        override_added = override_candidates[:override_extra]
        override_removed = remaining_removals[:override_extra]

        applied_set = set(current)
        applied_set.difference_update(removed)
        applied_set.difference_update(override_removed)
        applied_set.update(added)
        applied_set.update(override_added)

        applied_list = [s for s in desired if s in applied_set]
        extras = [s for s in current if s in applied_set and s not in desired_set]
        applied_list.extend(extras)
        applied_list = applied_list[: self.config.max_watch]

        applied_set = set(applied_list)
        desired_swaps = len(to_add)
        applied_swaps = len([s for s in applied_list if s in to_add])
        override_triggered = override_extra > 0

        missed = [s for s in desired if s not in applied_set]
        missed_new = [s for s in missed if s not in current_set]

        strong_threshold = None
        if desired:
            topk = desired[: min(self.config.strong_topk, len(desired))]
            topk_scores = [desired_scores.get(s, scores.get(s, 0.0)) for s in topk]
            topk_worst = min(topk_scores) if topk_scores else 0.0
            worst_applied = None
            if applied_list:
                applied_scores = [desired_scores.get(s, scores.get(s, 0.0)) for s in applied_list]
                worst_applied = min(applied_scores) if applied_scores else None
            if worst_applied is None:
                worst_applied = topk_worst
            strong_threshold = max(worst_applied + self.config.override_margin, topk_worst)

        missed_new_strong: List[str] = []
        reason_map: Dict[str, str] = {}
        for symbol in missed_new:
            score = desired_scores.get(symbol, scores.get(symbol, 0.0))
            rank = ranks.get(symbol, 9999)
            strong = False
            if strong_threshold is not None and score >= strong_threshold:
                strong = True
            if rank <= self.config.strong_rank_cutoff:
                strong = True
            if not strong:
                continue
            missed_new_strong.append(symbol)
            if symbol in remaining_adds_after and symbol not in override_candidates:
                reason_map[symbol] = "churn_limited"
            elif symbol in override_candidates and symbol not in override_added:
                reason_map[symbol] = "override_cap"
            else:
                reason_map[symbol] = "other"

        return ScanResult(
            ts_scan=ts_scan,
            raw_count=raw_count,
            filtered_count=filtered_count,
            desired_universe=desired,
            applied_universe=applied_list,
            current_universe=current,
            scores=desired_scores,
            ranks=ranks,
            to_add=to_add,
            to_remove=to_remove,
            desired_swaps=desired_swaps,
            allowed_swaps=allowed_swaps,
            override_extra=override_extra,
            applied_swaps=applied_swaps,
            override_triggered=override_triggered,
            missed_new_strong=missed_new_strong,
            reason_map=reason_map,
            trade_value=trade_value or {},
            change_rate=change_rate or {},
            event_score=event_score or {},
            vwap=vwap or {},
            intraday_high=intraday_high or {},
        )
