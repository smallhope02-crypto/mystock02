"""Helpers to classify why the evaluated universe is empty."""

from __future__ import annotations

from typing import Dict, Tuple


def classify_universe_empty(diag: Dict) -> Tuple[str, str]:
    """Return (reason, message) for an empty universe based on diagnostics.

    The diagnostics dict is expected to include:
    - rt_counts: dict[str, int]
    - today_union_count: int
    - rt_set_count: int
    - gate_on: bool
    - trigger_hits_count: int
    - infix: str
    - active_conditions: list
    These keys are treated defensively so the helper is robust in tests.
    """

    rt_counts = diag.get("rt_counts") or {}
    today_union_count = int(diag.get("today_union_count", 0) or 0)
    rt_set_count = int(diag.get("rt_set_count", 0) or 0)
    gate_on = bool(diag.get("gate_on"))
    trigger_hits_count = int(diag.get("trigger_hits_count", 0) or 0)
    infix = diag.get("infix", "")
    active_conditions = diag.get("active_conditions") or []

    # (C) 트리거 게이트 미충족 (게이트가 켜져 있다면 최우선)
    if gate_on and trigger_hits_count == 0:
        return (
            "gate_not_satisfied",
            "트리거 미발생으로 오늘누적 합산이 차단되었습니다.",
        )

    # (A) 전혀 수신된 조건 결과가 없는 경우
    if not today_union_count and all(v == 0 for v in rt_counts.values()):
        return (
            "no_condition_data",
            "프로그램이 조건 결과(TR/실시간)를 수신하지 못했습니다. '조건 실행(실시간 포함)' 후 [COND_EVT] 로그를 확인하세요.",
        )

    # (B) 표현식 평가 결과가 비어 있음
    if rt_counts:
        return (
            "expression_result_empty",
            f"표현식 결과가 비어 있습니다(infix={infix}, active={active_conditions}, rt_counts={rt_counts}).",
        )

    return ("unknown", "universe empty: 원인 알 수 없음")

