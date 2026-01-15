import pytest

from src.price_tick import shift_price_by_ticks, tick_size


def test_tick_size_brackets():
    assert tick_size(500) == 1
    assert tick_size(1500) == 1
    assert tick_size(2500) == 5
    assert tick_size(7500) == 10
    assert tick_size(15000) == 10
    assert tick_size(30000) == 50
    assert tick_size(70000) == 100
    assert tick_size(250000) == 500
    assert tick_size(600000) == 1000


def test_shift_crossing_boundaries_up():
    # 1999 -> +2 ticks => 2005 (1 tick to 2000, then 5 tick jump)
    assert shift_price_by_ticks(1999, 2) == 2005


def test_shift_crossing_boundaries_down():
    # 2001 -> -2 ticks => 1995 (first 5 down to 1996, then 1 down)
    assert shift_price_by_ticks(2001, -2) == 1995


def test_shift_respects_min_price():
    assert shift_price_by_ticks(1, -5) == 1
