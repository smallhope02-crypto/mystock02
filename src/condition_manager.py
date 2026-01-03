"""Expression-based condition evaluation for AND/OR with parentheses."""
from __future__ import annotations

import datetime
from typing import Dict, Iterable, List, Sequence, Set, Tuple


def _get_kst_timezone() -> datetime.tzinfo:
    """Return Asia/Seoul if available, otherwise a fixed UTC+9 offset.

    Some Windows installs lack ``tzdata`` so ``ZoneInfo('Asia/Seoul')``
    raises ``ZoneInfoNotFoundError``. Import and fallback locally to keep
    crashes away while still using KST semantics for day rollovers.
    """

    try:
        from zoneinfo import ZoneInfo  # type: ignore

        return ZoneInfo("Asia/Seoul")
    except Exception:  # pragma: no cover - fallback when tzdata is missing
        return datetime.timezone(datetime.timedelta(hours=9))


Token = Dict[str, str]


class ConditionManager:
    """Track condition-specific symbol sets and evaluate boolean expressions.

    The expression is provided as an infix token list (COND/OP/LPAREN/RPAREN).
    Precedence defaults to AND > OR. Parentheses are honored via a shunting
    yard conversion to postfix prior to evaluation.
    """

    PRECEDENCE = {"AND": 2, "OR": 1}

    def __init__(self) -> None:
        self.condition_sets_rt: Dict[str, Set[str]] = {}
        self.condition_sets_today: Dict[str, Set[str]] = {}
        self.tokens: List[Token] = []
        self._today: datetime.date | None = None
        self._tz = _get_kst_timezone()

    # ------------------------------------------------------------------
    def set_expression_tokens(self, tokens: Sequence[Token], reset_sets: bool = False) -> None:
        """Store the current infix tokens and ensure condition buckets exist.

        Args:
            tokens: iterable of token dicts with keys type/value/text/tooltip.
            reset_sets: when True, clears all tracked sets for active conditions.
        """

        self.tokens = list(tokens)
        active = {t.get("value") for t in self.tokens if t.get("type") == "COND" and t.get("value")}
        self._ensure_today()
        for name in active:
            key = str(name)
            self.condition_sets_rt.setdefault(key, set())
            self.condition_sets_today.setdefault(key, set())
        if reset_sets:
            for name in active:
                key = str(name)
                self.condition_sets_rt[key] = set()

    def reset_sets(self) -> None:
        for key in list(self.condition_sets_rt.keys()):
            self.condition_sets_rt[key] = set()
            self.condition_sets_today[key] = set()

    def _ensure_today(self, now: datetime.datetime | None = None) -> None:
        now = now or datetime.datetime.now(self._tz)
        if self._today != now.date():
            self._today = now.date()
            for key in list(self.condition_sets_today.keys()):
                self.condition_sets_today[key] = set()

    # ------------------------------------------------------------------
    def update_condition(self, name: str, symbols: Iterable[str]) -> None:
        self._ensure_today()
        key = str(name)
        bucket = set(symbols)
        self.condition_sets_rt[key] = bucket
        today_bucket = self.condition_sets_today.setdefault(key, set())
        today_bucket.update(bucket)

    def apply_event(self, name: str, code: str, event: str) -> None:
        key = str(name)
        self._ensure_today()
        bucket = self.condition_sets_rt.setdefault(key, set())
        today_bucket = self.condition_sets_today.setdefault(key, set())
        if event == "I":
            bucket.add(code)
            today_bucket.add(code)
        elif event == "D":
            bucket.discard(code)

    # ------------------------------------------------------------------
    def counts(self) -> Dict[str, int]:
        return {name: len(symbols) for name, symbols in self.condition_sets_rt.items()}

    # ------------------------------------------------------------------
    def _infix_to_postfix(self, tokens: Sequence[Token]) -> List[Token]:
        output: List[Token] = []
        ops: List[Token] = []
        for tok in tokens:
            ttype = tok.get("type")
            if ttype == "COND":
                output.append(tok)
            elif ttype == "OP":
                while ops and ops[-1].get("type") == "OP":
                    top = ops[-1]
                    if self.PRECEDENCE.get(top.get("value"), 0) >= self.PRECEDENCE.get(tok.get("value"), 0):
                        output.append(ops.pop())
                    else:
                        break
                ops.append(tok)
            elif ttype == "LPAREN":
                ops.append(tok)
            elif ttype == "RPAREN":
                while ops and ops[-1].get("type") != "LPAREN":
                    output.append(ops.pop())
                if ops and ops[-1].get("type") == "LPAREN":
                    ops.pop()
        while ops:
            output.append(ops.pop())
        return output

    def _evaluate_postfix(self, postfix: Sequence[Token], source: str = "rt") -> Set[str]:
        stack: List[Set[str]] = []
        for tok in postfix:
            ttype = tok.get("type")
            if ttype == "COND":
                src = self.condition_sets_today if source == "today" else self.condition_sets_rt
                stack.append(set(src.get(str(tok.get("value")), set())))
            elif ttype == "OP" and len(stack) >= 2:
                b, a = stack.pop(), stack.pop()
                if tok.get("value") == "AND":
                    stack.append(a & b)
                else:
                    stack.append(a | b)
        return stack[-1] if stack else set()

    def evaluate(self, source: str = "rt") -> Tuple[Set[str], List[Token]]:
        """Return (final_set, postfix_tokens) for current tokens."""

        self._ensure_today()
        if not self.tokens:
            return set(), []
        postfix = self._infix_to_postfix(self.tokens)
        final_set = self._evaluate_postfix(postfix, source=source)
        return final_set, postfix

    def get_bucket(self, name: str, source: str = "rt") -> Set[str]:
        self._ensure_today()
        src = self.condition_sets_today if source == "today" else self.condition_sets_rt
        return set(src.get(str(name), set()))

    def render_infix(self, tokens: Sequence[Token] | None = None) -> str:
        src = tokens if tokens is not None else self.tokens
        parts: List[str] = []
        for tok in src:
            text = tok.get("text") or tok.get("value", "")
            parts.append(str(text))
        return " ".join(parts) if parts else "(empty)"

    def postfix_text(self, tokens: Sequence[Token]) -> str:
        parts: List[str] = []
        for tok in tokens:
            if tok.get("type") == "OP":
                parts.append(tok.get("value", ""))
            else:
                parts.append(tok.get("text") or tok.get("value", ""))
        return " ".join(parts)

