"""Sanity checks for KiwoomClient placeholder behaviors."""

from src.kiwoom_client import KiwoomClient


def test_real_balance_dummy_returns_int():
    client = KiwoomClient(account_no="12345678")
    balance = client.get_real_balance()
    assert isinstance(balance, int)
    assert balance >= 0


def test_list_conditions_returns_dummy_items():
    client = KiwoomClient(account_no="12345678")
    tuples = client.get_condition_list()
    assert isinstance(tuples, list)
    assert all(isinstance(item, tuple) and len(item) == 2 for item in tuples)
    names = client.list_conditions()
    assert isinstance(names, list)
    assert all(isinstance(name, str) for name in names)


def test_condition_universe_dummy_falls_back():
    client = KiwoomClient(account_no="12345678")
    universe = client.get_condition_universe("단기급등_체크")
    assert isinstance(universe, list)
    assert all(isinstance(code, str) for code in universe)
