from src.universe_diag import classify_universe_empty


def test_no_condition_data():
    reason, msg = classify_universe_empty({"rt_counts": {}, "today_union_count": 0})
    assert reason == "no_condition_data"
    assert "조건 결과" in msg


def test_gate_not_satisfied():
    reason, _ = classify_universe_empty(
        {
            "rt_counts": {"A": 0},
            "today_union_count": 0,
            "gate_on": True,
            "trigger_hits_count": 0,
        }
    )
    assert reason == "gate_not_satisfied"


def test_expression_empty():
    reason, _ = classify_universe_empty(
        {
            "rt_counts": {"A": 2, "B": 1},
            "today_union_count": 0,
            "rt_set_count": 0,
            "infix": "1 AND 2",
            "active_conditions": ["1", "2"],
        }
    )
    assert reason == "expression_result_empty"
