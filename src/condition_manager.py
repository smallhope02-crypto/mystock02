"""Manage multiple condition results and AND/OR combinations."""

from __future__ import annotations

from typing import Dict, Iterable, List, Set


class ConditionManager:
    """Track condition-specific symbol sets and combine them."""

    def __init__(self) -> None:
        self.condition_sets: Dict[str, Set[str]] = {}
        self.active_conditions: List[str] = []

    def reset(self, active_conditions: Iterable[str]) -> None:
        self.active_conditions = list(active_conditions)
        for name in self.active_conditions:
            self.condition_sets[name] = set()

    def update_condition(self, name: str, symbols: Iterable[str]) -> None:
        self.condition_sets[name] = set(symbols)

    def apply_event(self, name: str, code: str, event: str) -> None:
        if name not in self.condition_sets:
            return
        target = self.condition_sets.setdefault(name, set())
        if event == "I":
            target.add(code)
        elif event == "D" and code in target:
            target.remove(code)

    def combined(self, logic: str) -> List[str]:
        logic = logic.upper()
        sets = [self.condition_sets.get(n, set()) for n in self.active_conditions]
        if not sets:
            return []
        if logic == "AND":
            base = set(sets[0])
            for s in sets[1:]:
                base &= set(s)
            return sorted(base)
        combined: Set[str] = set()
        for s in sets:
            combined |= set(s)
        return sorted(combined)

    def counts(self) -> Dict[str, int]:
        return {name: len(symbols) for name, symbols in self.condition_sets.items()}
