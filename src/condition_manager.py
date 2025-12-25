"""Manage multiple condition results with grouped AND/OR evaluation."""

from __future__ import annotations

from typing import Dict, Iterable, List, Sequence, Set, Tuple


class ConditionManager:
    """Track condition-specific symbol sets and combine them by groups.

    Groups represent OR buckets, and the final universe is the intersection of
    all group unions. Each condition is addressed by its name/key.
    """

    def __init__(self) -> None:
        self.condition_sets: Dict[str, Set[str]] = {}
        self.groups: List[List[str]] = []
        self.active_conditions: List[str] = []

    # ------------------------------------------------------------------
    def set_groups(self, groups: Sequence[Sequence[str]]) -> None:
        """Set the active groups (list of OR buckets).

        Empty groups are ignored during evaluation, but callers should avoid
        them. Condition sets are initialized if missing.
        """

        cleaned: List[List[str]] = []
        for group in groups:
            uniq: List[str] = []
            for name in group:
                if name and name not in uniq:
                    uniq.append(name)
            if uniq:
                cleaned.append(uniq)
        self.groups = cleaned
        self.active_conditions = sorted({name for grp in cleaned for name in grp})
        for name in self.active_conditions:
            self.condition_sets.setdefault(name, set())

    def reset_sets(self) -> None:
        """Clear all tracked condition symbol sets."""

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

    # ------------------------------------------------------------------
    def evaluate(self) -> Tuple[Set[str], List[Set[str]]]:
        """Return (final_set, group_sets) using OR-inside/AND-between rule."""

        group_sets: List[Set[str]] = []
        for group in self.groups:
            union: Set[str] = set()
            for name in group:
                union |= self.condition_sets.get(name, set())
            group_sets.append(union)

        if not group_sets or any(len(g) == 0 for g in group_sets):
            return set(), group_sets

        final_set = set(group_sets[0])
        for g in group_sets[1:]:
            final_set &= g
        return final_set, group_sets

    def counts(self) -> Dict[str, int]:
        return {name: len(symbols) for name, symbols in self.condition_sets.items()}

