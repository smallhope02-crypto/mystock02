import pytest

from src.condition_manager import ConditionManager


def build_tokens(expr):
    # expr list of tuples (type,value,text)
    tokens = []
    for ttype, value, text in expr:
        tok = {"type": ttype, "value": value}
        if text:
            tok["text"] = text
        tokens.append(tok)
    return tokens


def test_expression_and_or_precedence_with_parentheses():
    manager = ConditionManager()
    manager.update_condition("1", {"A", "B"})
    manager.update_condition("2", {"B", "C"})
    manager.update_condition("3", {"A", "C", "D"})
    manager.update_condition("4", {"A", "B", "C", "D"})

    tokens = build_tokens(
        [
            ("COND", "1", "1"),
            ("OP", "AND", "AND"),
            ("LPAREN", "(", "("),
            ("COND", "2", "2"),
            ("OP", "OR", "OR"),
            ("COND", "3", "3"),
            ("RPAREN", ")", ")"),
            ("OP", "AND", "AND"),
            ("COND", "4", "4"),
        ]
    )
    manager.set_expression_tokens(tokens)
    final_set, postfix = manager.evaluate()

    assert manager.render_infix(tokens) == "1 AND ( 2 OR 3 ) AND 4"
    assert manager.postfix_text(postfix) == "1 2 3 OR AND 4 AND"
    # (2 OR 3) => {A,B,C,D}; intersect with 1 => {A,B}; intersect with 4 => {A,B}
    assert final_set == {"A", "B"}


def test_expression_or_only():
    manager = ConditionManager()
    manager.update_condition("1", {"X"})
    manager.update_condition("2", {"Y"})
    tokens = build_tokens([("COND", "1", "1"), ("OP", "OR", "OR"), ("COND", "2", "2")])
    manager.set_expression_tokens(tokens)
    final_set, postfix = manager.evaluate()
    assert final_set == {"X", "Y"}
    assert manager.postfix_text(postfix) == "1 2 OR"

