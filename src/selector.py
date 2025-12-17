"""Universe selection logic with pluggable scoring hooks."""

import logging
import random
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class CandidateScore:
    symbol: str
    score: float


class UniverseSelector:
    """Select tradable symbols using placeholder scoring steps.

    Each scoring method is kept separate so that future API integrations can
    replace the dummy logic with real data (e.g., market breadth, news, flows).
    """

    def __init__(self, kiwoom_client: Optional[object] = None):
        self.scorers: List[Callable[[List[str]], Dict[str, float]]] = [
            self._score_market_trend,
            self._score_theme_alignment,
            self._score_flow_and_news,
        ]
        # KiwoomClient is injected lazily to avoid circular imports
        self.kiwoom_client = kiwoom_client
        self.external_universe: List[str] = []

    def attach_client(self, client: object) -> None:
        """Attach a KiwoomClient-like object after construction."""

        self.kiwoom_client = client

    def set_external_universe(self, universe: List[str]) -> None:
        """Override the selector with an externally provided universe."""

        self.external_universe = list(dict.fromkeys(universe))
        logger.info("[유니버스] external_universe set: %d개", len(self.external_universe))

    def add_to_universe(self, symbol: str) -> None:
        if symbol not in self.external_universe:
            self.external_universe.append(symbol)
            logger.info("[유니버스] external_universe update: +%s (size=%d)", symbol, len(self.external_universe))

    def remove_from_universe(self, symbol: str) -> None:
        before = len(self.external_universe)
        self.external_universe = [s for s in self.external_universe if s != symbol]
        if len(self.external_universe) != before:
            logger.info("[유니버스] external_universe update: -%s (size=%d)", symbol, len(self.external_universe))

    def select(self, condition_name: str) -> List[str]:
        """Return a sorted universe of symbols for the given condition."""
        if self.external_universe:
            logger.info("[유니버스] selector 사용 목록: external_universe 우선 적용 (%d개)", len(self.external_universe))
            return list(self.external_universe)

        base_universe = self._load_base_universe(condition_name)
        composite_score: Dict[str, float] = {symbol: 0.0 for symbol in base_universe}

        for scorer in self.scorers:
            scores = scorer(base_universe)
            for symbol, value in scores.items():
                composite_score[symbol] = composite_score.get(symbol, 0.0) + value

        ranked = sorted([CandidateScore(symbol, score) for symbol, score in composite_score.items()], key=lambda c: c.score, reverse=True)
        selected = [c.symbol for c in ranked[:5]]
        logger.info("Selected universe from %s: %s", condition_name, selected)
        return selected

    def _load_base_universe(self, condition_name: str) -> List[str]:
        """Load a baseline universe.

        TODO: 실제 API 연동 시 구현
        """
        if self.kiwoom_client:
            try:
                universe = getattr(self.kiwoom_client, "get_condition_universe")(condition_name)
                if universe:
                    return universe
            except Exception as exc:  # pragma: no cover - defensive fallback
                logger.exception("Kiwoom condition universe failed: %s", exc)

        random.seed(condition_name)
        return [f"SYM{num:03d}" for num in random.sample(range(1, 30), 10)]

    def _score_market_trend(self, symbols: List[str]) -> Dict[str, float]:
        """Score symbols by market trend (dummy implementation)."""
        random.seed("trend" + ",".join(symbols))
        return {s: random.uniform(-1, 1) for s in symbols}

    def _score_theme_alignment(self, symbols: List[str]) -> Dict[str, float]:
        """Score symbols by theme alignment (dummy implementation)."""
        random.seed("theme" + ",".join(symbols))
        return {s: random.uniform(-0.5, 1.5) for s in symbols}

    def _score_flow_and_news(self, symbols: List[str]) -> Dict[str, float]:
        """Score symbols by flow/news signals (dummy implementation)."""
        random.seed("news" + ",".join(symbols))
        return {s: random.uniform(-0.2, 1.2) for s in symbols}
