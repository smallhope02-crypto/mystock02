"""Sanity checks for KiwoomClient placeholder behaviors."""

from src.kiwoom_client import KiwoomClient


def test_real_balance_dummy_returns_int():
    client = KiwoomClient(account_no="12345678")
    balance = client.get_real_balance()
    assert isinstance(balance, int)
    assert balance >= 0


def test_list_conditions_returns_dummy_items():
    client = KiwoomClient(account_no="12345678")
    conditions = client.list_conditions()
    assert conditions
    assert all(isinstance(name, str) for name in conditions)
